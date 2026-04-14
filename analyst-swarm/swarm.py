"""
Analyst Swarm Orchestrator — runs all investment analyst agents on a schedule.
Supports Claude API and Ollama as LLM backends.
"""

import asyncio
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from data_digest import (
    auto_digest,
    digest_analyst_summaries,
    digest_fundamentals_for_security,
    digest_insider_signals,
    digest_news,
    digest_technical,
)

# API key for backend authentication
_API_KEY = os.environ.get("API_KEY", "")
_AUTH_HEADERS = {"X-API-Key": _API_KEY} if _API_KEY else {}

# Telegram notifications (for fallback alerts)
_TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Track whether we've already notified about CLI auth failure (avoid spam)
_cli_fallback_notified = False


async def send_telegram(text: str) -> bool:
    """Send a Telegram message (force-sends, ignores quiet hours)."""
    if not _TG_TOKEN or not _TG_CHAT_ID:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
                json={
                    "chat_id": _TG_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            return resp.status_code == 200
    except Exception:
        return False

# ── Config ──

def load_config() -> dict:
    """Load config from config.local.yaml (priority) or config.yaml."""
    config_dir = Path(__file__).parent
    local = config_dir / "config.local.yaml"
    default = config_dir / "config.yaml"
    path = local if local.exists() else default
    with open(path) as f:
        cfg = yaml.safe_load(f)

    # Env var overrides
    if os.environ.get("ANTHROPIC_API_KEY"):
        cfg.setdefault("claude", {})["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("LLM_PROVIDER"):
        cfg["llm_provider"] = os.environ["LLM_PROVIDER"]
    if os.environ.get("OLLAMA_BASE_URL"):
        cfg.setdefault("ollama", {})["base_url"] = os.environ["OLLAMA_BASE_URL"]
    if os.environ.get("OLLAMA_MODEL"):
        cfg.setdefault("ollama", {})["model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("CLAUDE_MODEL"):
        cfg.setdefault("claude", {})["model"] = os.environ["CLAUDE_MODEL"]
    if os.environ.get("CLAUDE_CLI_BINARY"):
        cfg.setdefault("claude_cli", {})["binary"] = os.environ["CLAUDE_CLI_BINARY"]
    if os.environ.get("CLAUDE_CLI_MODEL"):
        cfg.setdefault("claude_cli", {})["model"] = os.environ["CLAUDE_CLI_MODEL"]
    if os.environ.get("BACKEND_URL"):
        cfg["backend_url"] = os.environ["BACKEND_URL"]
    if os.environ.get("MAX_PARALLEL"):
        cfg["max_parallel"] = int(os.environ["MAX_PARALLEL"])

    return cfg


# ── LLM Backends ──

async def call_claude(prompt: str, system: str, cfg: dict) -> str:
    """Call Claude API."""
    api_key = cfg["claude"]["api_key"]
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": cfg["claude"]["model"],
                "max_tokens": cfg["claude"].get("max_tokens", 8192),
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


async def call_ollama(prompt: str, system: str, cfg: dict) -> str:
    """Call Ollama API."""
    base_url = cfg["ollama"]["base_url"].rstrip("/")

    async with httpx.AsyncClient(timeout=1800) as client:
        resp = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": cfg["ollama"]["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {
                    "num_predict": cfg["ollama"].get("max_tokens", 8192),
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


async def call_claude_cli(prompt: str, system: str, cfg: dict, timeout: int = 600) -> str:
    """Call Claude via the claude CLI (uses company subscription, not API credits)."""
    import subprocess
    import tempfile

    cli_cfg = cfg.get("claude_cli", {})
    claude_bin = cli_cfg.get("binary", "claude")
    model = cli_cfg.get("model", "")  # empty = use default

    # Combine system + user prompt for the CLI
    full_prompt = f"{system}\n\n---\n\n{prompt}"

    # Write prompt to a temp file to avoid shell escaping issues
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(full_prompt)
        tmp_path = f.name

    try:
        cmd = [claude_bin, "-p", "--output-format", "text"]
        if model:
            cmd.extend(["--model", model])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        with open(tmp_path, "rb") as f:
            stdin_data = f.read()

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data),
            timeout=timeout,
        )

        if proc.returncode != 0:
            err = stderr.decode().strip()
            raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {err[:500]}")

        return stdout.decode().strip()
    finally:
        os.unlink(tmp_path)


_effective_provider: str = "unknown"  # tracks which LLM actually ran last


def get_llm_tag() -> str:
    """Return a tag indicating which LLM provider generated the content."""
    return f"llm:{_effective_provider}"


async def call_llm(prompt: str, system: str, cfg: dict, timeout: int = 600) -> str:
    """Route to the configured LLM backend. Falls back to Ollama if claude_cli fails."""
    global _cli_fallback_notified, _effective_provider
    provider = cfg.get("llm_provider", "claude")

    if provider == "claude":
        _effective_provider = "claude"
        return await call_claude(prompt, system, cfg)
    elif provider == "claude_cli":
        try:
            result = await call_claude_cli(prompt, system, cfg, timeout=timeout)
            _effective_provider = "claude"
            return result
        except Exception as e:
            err_msg = str(e)
            print(f"  [llm] claude_cli failed: {err_msg[:200]}", flush=True)

            # Check if Ollama is configured as fallback
            ollama_cfg = cfg.get("ollama", {})
            if not ollama_cfg.get("base_url") or not ollama_cfg.get("model"):
                raise  # No fallback available

            print(f"  [llm] Falling back to Ollama ({ollama_cfg['model']})...", flush=True)

            # Send Telegram alert (once per session to avoid spam)
            if not _cli_fallback_notified:
                _cli_fallback_notified = True
                await send_telegram(
                    "<b>⚠ Claude CLI Auth Failed</b>\n\n"
                    f"Error: <code>{err_msg[:300]}</code>\n\n"
                    f"Falling back to Ollama ({ollama_cfg['model']}). "
                    "Run <code>claude /login</code> on the host to re-authenticate."
                )

            _effective_provider = "ollama"
            return await call_ollama(prompt, system, cfg)
    elif provider == "ollama":
        _effective_provider = "ollama"
        return await call_ollama(prompt, system, cfg)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


# ── Status Reporting ──

async def report_status(backend_url: str, status: str, agent: str | None = None,
                        completed: int = 0, total: int = 0, message: str | None = None):
    """Report swarm status to the backend (stored in Redis)."""
    try:
        async with httpx.AsyncClient(timeout=5, base_url=backend_url, headers=_AUTH_HEADERS) as client:
            await client.post("/swarm/status", json={
                "status": status,
                "agent": agent,
                "completed": completed,
                "total": total,
                "message": message,
            })
    except Exception:
        pass  # Non-critical — don't fail the swarm over status reporting


# ── Post-Swarm Health Check ──


async def run_health_check(backend_url: str) -> None:
    """Check data quality after swarm run and send Telegram alert if issues found.

    Checks:
    1. Pipeline staleness — any pipeline that hasn't succeeded in >24h
    2. Holdings with null prices — securities we own but can't value
    3. Risk metrics — should be computable if we have price history
    4. Analyst report quality — flag reports with "no data" / "unavailable"
    """
    issues: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=30, base_url=backend_url, headers=_AUTH_HEADERS) as client:
            # 1. Pipeline staleness
            try:
                resp = await client.get("/pipelines")
                if resp.status_code == 200:
                    pipelines = resp.json().get("data", [])
                    now = datetime.now(timezone.utc)
                    for p in pipelines:
                        name = p.get("name", "?")
                        last_success = p.get("lastSuccessAt")
                        last_failure = p.get("lastFailureAt")
                        if last_failure and not last_success:
                            issues.append(f"⚠️ <b>{name}</b>: never succeeded, last failure exists")
                        elif last_success:
                            try:
                                success_dt = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
                                hours_ago = (now - success_dt).total_seconds() / 3600
                                if hours_ago > 48:
                                    issues.append(
                                        f"⚠️ <b>{name}</b>: stale ({int(hours_ago)}h since last success)"
                                    )
                            except (ValueError, TypeError):
                                pass
            except Exception as e:
                issues.append(f"❌ Pipeline check failed: {e}")

            # 2. Holdings with null prices
            try:
                resp = await client.get("/portfolio/holdings")
                if resp.status_code == 200:
                    holdings = resp.json().get("data", [])
                    null_price = [
                        h["ticker"] for h in holdings
                        if h.get("currentPriceCents") is None and float(h.get("quantity", 0)) > 0
                    ]
                    if null_price:
                        issues.append(
                            f"⚠️ <b>Missing prices</b>: {', '.join(null_price[:10])}"
                            + (f" (+{len(null_price)-10} more)" if len(null_price) > 10 else "")
                        )
            except Exception as e:
                issues.append(f"❌ Holdings check failed: {e}")

            # 3. Risk metrics
            try:
                resp = await client.get("/risk")
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    metrics = data.get("metrics")
                    if not metrics:
                        issues.append("⚠️ <b>Risk metrics</b>: unavailable (no price history?)")
                elif resp.status_code == 500:
                    issues.append("❌ <b>Risk endpoint</b>: 500 error")
            except Exception as e:
                issues.append(f"❌ Risk check failed: {e}")

            # 4. Latest analyst reports quality
            try:
                resp = await client.get("/swarm/reports?limit=20")
                if resp.status_code == 200:
                    reports = resp.json().get("data", [])
                    bad_keywords = ["unavailable", "no data", "api error", "endpoint returned no",
                                    "fabricated", "don't have access", "cannot perform"]
                    flagged = []
                    for r in reports:
                        content = (r.get("content") or "").lower()
                        agent = r.get("agentName", "?")
                        for kw in bad_keywords:
                            if kw in content:
                                flagged.append(agent)
                                break
                    if flagged:
                        unique = sorted(set(flagged))
                        issues.append(
                            f"⚠️ <b>Analyst data gaps</b>: {', '.join(unique)} "
                            f"reported missing/unavailable data"
                        )
            except Exception:
                pass  # Reports endpoint may not exist — non-critical

    except Exception as e:
        issues.append(f"❌ Health check failed: {e}")

    # Send Telegram summary
    if issues:
        msg = "🔍 <b>Post-Swarm Health Check</b>\n\n"
        msg += "\n".join(issues)
        msg += f"\n\n<i>{len(issues)} issue(s) found</i>"
        await send_telegram(msg)
        print(f"[health] {len(issues)} issues found, Telegram alert sent", flush=True)
    else:
        print("[health] All checks passed", flush=True)


# ── Watchlist Rotation ──

_OFFSET_FILE = Path(__file__).parent / ".watchlist_offset"

def _get_watchlist_offset(backend_url: str) -> int:
    try:
        return int(_OFFSET_FILE.read_text().strip())
    except Exception:
        return 0

def _set_watchlist_offset(backend_url: str, offset: int):
    try:
        _OFFSET_FILE.write_text(str(offset))
    except Exception:
        pass


# ── Data Fetching ──

async def fetch_data(backend_url: str, endpoints: list[str]) -> dict[str, str]:
    """Fetch data from multiple API endpoints."""
    results = {}
    async with httpx.AsyncClient(timeout=60, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        for ep in endpoints:
            try:
                resp = await client.get(ep)
                if resp.status_code == 200:
                    results[ep] = resp.text

                    # For /watchlists/, also fetch each watchlist's items (with rotation)
                    if ep == "/watchlists/":
                        try:
                            wl_data = resp.json().get("data", [])
                            all_items = []
                            for wl in wl_data:
                                if wl.get("itemCount", 0) > 0:
                                    wl_resp = await client.get(f"/watchlists/{wl['id']}")
                                    if wl_resp.status_code == 200:
                                        wl_detail = wl_resp.json().get("data", {})
                                        for item in wl_detail.get("items", []):
                                            item["watchlistName"] = wl["name"]
                                            all_items.append(item)
                            # Rotate: send ~20 items per run, advance offset each time
                            batch_size = 35
                            offset = _get_watchlist_offset(backend_url)
                            if len(all_items) > batch_size:
                                start = offset % len(all_items)
                                batch = all_items[start:start + batch_size]
                                if len(batch) < batch_size:
                                    batch += all_items[:batch_size - len(batch)]
                                _set_watchlist_offset(backend_url, offset + batch_size)
                                remaining = len(all_items) - batch_size
                                results["/watchlists/items"] = json.dumps({
                                    "data": batch,
                                    "meta": {"total": len(all_items), "batchSize": batch_size,
                                             "offset": start, "remaining": remaining},
                                })
                            else:
                                results["/watchlists/items"] = json.dumps({"data": all_items})
                        except Exception:
                            pass
                else:
                    results[ep] = f"ERROR {resp.status_code}"
            except Exception as e:
                results[ep] = f"ERROR: {e}"
    # Split the unified /risk response into labelled sub-sections
    # so agents see /risk/metrics, /risk/stress-tests, etc. as separate data
    if "/risk" in results and not results["/risk"].startswith("ERROR"):
        try:
            risk_data = json.loads(results["/risk"]).get("data", {})
            for key, label in [
                ("metrics", "/risk/metrics"),
                ("stressTests", "/risk/stress-tests"),
                ("glidepath", "/risk/glidepath"),
                ("correlation", "/risk/correlation"),
                ("concentration", "/risk/concentration"),
            ]:
                val = risk_data.get(key)
                if val is not None:
                    results[label] = json.dumps({"data": val})
                else:
                    results[label] = "No data available"
        except (json.JSONDecodeError, TypeError):
            pass

    return results


# ── Agent Definitions ──

# Data endpoints each agent needs
AGENT_DATA = {
    "research-analyst": [
        "/portfolio/holdings", "/portfolio/summary", "/fundamentals?limit=200",
        "/news?limit=20", "/insiders/signals", "/prices/latest",
        "/watchlists/",
    ],
    "risk-manager": [
        "/portfolio/holdings", "/portfolio/summary", "/risk",
        "/macro/regime",
    ],
    "quant-analyst": [
        "/portfolio/holdings", "/portfolio/summary", "/risk",
        "/fundamentals?limit=200", "/screener/munger", "/macro/regime",
    ],
    "macro-strategist": [
        "/macro/summary", "/macro/regime", "/portfolio/summary",
        "/news?limit=30", "/portfolio/holdings",
    ],
    "fixed-income-analyst": [
        "/portfolio/holdings", "/portfolio/summary", "/macro/summary",
        "/macro/regime", "/dividends/income", "/dividends/upcoming",
    ],
    "tax-strategist": [
        "/portfolio/holdings", "/portfolio/summary",
        "/transactions?limit=50", "/tax/lots", "/tax/gains",
        "/tax/osakesaastotili",
    ],
    "technical-analyst": [
        "/portfolio/holdings", "/screener/munger",
        "/charts/heatmap?source=holdings&period=1W",
        "/watchlists/",
    ],
    "compliance-officer": [
        "/portfolio/holdings", "/portfolio/summary", "/insiders/signals",
        "/news?limit=10", "/alerts?status=active", "/transactions?limit=50",
        "/risk", "/macro/regime", "/pipelines",
        "/tax/lots", "/tax/osakesaastotili",
    ],
    "portfolio-manager": [
        "/deployment-plans/current",
        "/portfolio/holdings", "/portfolio/summary",
        "/transactions?type=buy&limit=50", "/transactions?limit=50",
        "/dividends/upcoming", "/risk",
        "/watchlists/", "/screener/munger", "/insiders/signals",
        "/news?limit=20", "/macro/summary", "/macro/regime",
        "/fundamentals?limit=200", "/recommendations?status=active&limit=50",
        "/research/notes?tag=research-analyst&limit=100",
        "/research/notes?tag=analyst_report&limit=10",
    ],
}


def load_agent_prompt(agent_name: str) -> str:
    """Load agent definition from agents/ directory (mounted in Docker)."""
    # Try mounted path first (Docker), then relative path (local dev)
    for agents_dir in [
        Path(__file__).parent / "agents",
        Path(__file__).parent.parent / ".claude" / "agents",
    ]:
        path = agents_dir / f"{agent_name}.md"
        if path.exists():
            return path.read_text()
    raise FileNotFoundError(f"Agent definition not found for: {agent_name}")


def build_prompt(agent_name: str, agent_def: str, data: dict[str, str],
                 date_str: str, cfg: dict | None = None) -> tuple[str, str]:
    """Build system prompt and user prompt for an agent."""
    use_digest = cfg.get("digest_data", False) if cfg else False
    use_short = cfg.get("short_prompts", False) if cfg else False

    system = f"""You are the {agent_name} for the Bloomvalley investment terminal.
Follow your agent definition exactly. Today's date is {date_str}.
ALL backend API data has been pre-fetched and is provided below — do NOT attempt to make API calls yourself.
If a data section shows an error, that data is unavailable — work with what you have, do not ask for permission to fetch it.
Produce your complete analysis report. Be specific with numbers, dates, and actionable recommendations."""

    if use_digest:
        digested = auto_digest(data)
        data_section = "\n\n".join(
            f"### {label}\n{content}"
            for label, content in digested.items()
            if content
        )
    else:
        data_section = "\n\n".join(
            f"### Data from {ep}\n```json\n{content[:15000]}\n```"
            if not content.startswith("ERROR")
            else f"### Data from {ep}\n*Unavailable: {content}*"
            for ep, content in data.items()
        )

    prompt_def = _build_short_prompt(agent_name, agent_def) if use_short else agent_def

    user_prompt = f"""# Agent Definition

{prompt_def}

# Pre-fetched API Data

{data_section}

# Instructions

Analyze the data above and produce your complete report following the format in your agent definition.
Today is {date_str}. Be concrete and specific."""

    return system, user_prompt


def _build_short_prompt(agent_name: str, full_def: str) -> str:
    """Extract essential sections from a full agent definition for smaller models.

    Keeps: role paragraph, data access list, output format section.
    Strips: lengthy methodology explanations, detailed frameworks.
    """
    lines = full_def.split("\n")
    result = []
    in_output_section = False
    in_role_section = True
    role_lines = 0

    for line in lines:
        # Always keep headings
        if line.startswith("#"):
            header_lower = line.lower()
            if any(k in header_lower for k in ["output", "format", "report structure",
                                                  "deliverable", "response format"]):
                in_output_section = True
                in_role_section = False
                result.append(line)
                continue
            elif any(k in header_lower for k in ["data", "api", "endpoint", "access"]):
                in_output_section = False
                in_role_section = False
                result.append(line)
                continue
            elif any(k in header_lower for k in ["framework", "methodology", "process",
                                                    "workflow", "detailed", "guidelines"]):
                in_output_section = False
                in_role_section = False
                continue  # Skip these sections entirely
            else:
                in_output_section = False
                in_role_section = False
                continue  # Skip unknown sections

        # Keep the role description (first ~15 lines before first heading)
        if in_role_section:
            role_lines += 1
            if role_lines <= 20:
                result.append(line)
            continue

        # Keep output format section
        if in_output_section:
            result.append(line)

    return "\n".join(result)


# ── Pipeline Refresh ──

async def refresh_pipelines(cfg: dict):
    """Trigger all data pipelines and wait for completion."""
    backend_url = cfg["backend_url"]
    pipelines = cfg.get("pipelines", [])
    timeout = cfg.get("pipeline_timeout", 300)

    if not pipelines:
        return

    print(f"[swarm] Refreshing {len(pipelines)} data pipelines...", flush=True)

    async with httpx.AsyncClient(timeout=30, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        for p in pipelines:
            try:
                resp = await client.post(f"/pipelines/{p}/run")
                status = "triggered" if resp.status_code == 200 else f"error {resp.status_code}"
                print(f"  {p}: {status}", flush=True)
            except Exception as e:
                print(f"  {p}: FAILED ({e})", flush=True)

    # Wait for pipelines to finish
    print(f"[swarm] Waiting up to {timeout}s for pipelines...", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        await asyncio.sleep(10)
        try:
            async with httpx.AsyncClient(timeout=10, base_url=backend_url, headers=_AUTH_HEADERS) as client:
                resp = await client.get("/pipelines")
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    running = [p["name"] for p in data if p.get("lastRun", {}).get("status") == "running"]
                    if not running:
                        print("[swarm] All pipelines complete.", flush=True)
                        return
                    print(f"  Still running: {', '.join(running)}", flush=True)
        except Exception:
            pass

    print("[swarm] Pipeline timeout reached, proceeding with available data.", flush=True)


# ── Store Results ──

async def store_report(backend_url: str, agent_name: str, report: str):
    """Store the agent report as a research note."""
    async with httpx.AsyncClient(timeout=30, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        try:
            await client.post("/research/notes", json={
                "title": f"{agent_name.replace('-', ' ').title()} — {datetime.now().strftime('%Y-%m-%d')}",
                "thesis": report[:60000],
                "tags": ["analyst_report", agent_name, "swarm", get_llm_tag()],
            })
        except Exception as e:
            print(f"  [!] Failed to store report for {agent_name}: {e}", flush=True)


# ── Research Analyst: Per-Security Extraction ──

# Matches "## 1. TICKER — Name", "### 1. TICKER — Name", and "## W-1. TICKER — Name"
_SECTION_RE = re.compile(
    r"^#{2,3} (?:W-)?(\d+)\. ([A-Z][A-Z0-9._-]+) — (.+?)$",
    re.MULTILINE,
)


def _strip_foreign_fundamentals(text: str, ticker: str) -> str:
    """Remove any FUNDAMENTALS: blocks that don't belong to the target ticker."""
    return re.sub(
        r"\n*FUNDAMENTALS:\s+(?!" + re.escape(ticker) + r"\b)\S+.*",
        "",
        text,
        flags=re.DOTALL,
    ).rstrip()


def _parse_research_sections(report: str) -> list[dict]:
    """Split a research analyst report into per-security sections."""
    matches = list(_SECTION_RE.finditer(report))
    if not matches:
        return []

    sections = []
    seen_tickers: set[str] = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        body = report[start:end].strip()
        ticker = m.group(2)
        name = m.group(3).strip()
        is_watchlist = body.startswith("## W-")

        # Deduplicate — if same ticker appears twice (held + watchlist), keep held
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)

        # Extract structured fields from the section text
        # Watchlist briefs use **Bull case** inline; held positions use ### Bull Case headings
        bull = (_extract_field(body, r"### Bull [Cc]ase[^#\n]*\n(.+?)(?=\n###|\n## |\Z)")
                or _extract_field(body, r"\*\*Bull [Cc]ase[^*]*\*\*[:\s—–-]*(.+?)(?:\n\n|\n\*\*|\Z)"))
        bear = (_extract_field(body, r"### Bear [Cc]ase[^#\n]*\n(.+?)(?=\n###|\n## |\Z)")
                or _extract_field(body, r"\*\*Bear [Cc]ase[^*]*\*\*[:\s—–-]*(.+?)(?:\n\n|\n\*\*|\Z)"))
        base = (_extract_field(body, r"### Base [Cc]ase[^#\n]*\n(.+?)(?=\n###|\n## |\Z)")
                or _extract_field(body, r"\*\*Base [Cc]ase[^*]*\*\*[:\s—–-]*(.+?)(?:\n\n|\n\*\*|\Z)"))
        moat = _extract_moat(body)
        verdict = _extract_field(body, r"\*\*Verdict[:\s]*([A-Z]+)\*\*")

        sections.append({
            "ticker": ticker,
            "name": name,
            "is_watchlist": is_watchlist,
            "body": body,
            "bull_case": bull,
            "bear_case": bear,
            "base_case": base,
            "moat_rating": moat,
            "verdict": verdict,
        })

    return sections


def _extract_field(text: str, pattern: str) -> str | None:
    """Extract a single field from section text using regex."""
    m = re.search(pattern, text, re.DOTALL)
    if m:
        val = m.group(1).strip()
        # Clean up — remove trailing --- separators
        val = re.sub(r"\n---\s*$", "", val).strip()
        return val if val else None
    return None


def _extract_moat(text: str) -> str | None:
    """Extract moat rating (none/narrow/wide) from section text."""
    m = re.search(r"[Mm]oat.*?:\s*\*?\*?(none|narrow|wide)\*?\*?", text, re.IGNORECASE)
    return m.group(1).lower() if m else None


async def extract_per_security_notes(report: str, backend_url: str, date_str: str,
                                     llm_tag: str | None = None):
    """Parse research analyst report into per-security research notes and POST them."""
    sections = _parse_research_sections(report)
    if not sections:
        print("  [research] No per-security sections found to extract", flush=True)
        return

    # Resolve tickers to security IDs
    async with httpx.AsyncClient(timeout=30, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        try:
            sec_resp = await client.get("/securities?limit=500")
            securities = {s["ticker"]: s["id"] for s in sec_resp.json().get("data", [])}
        except Exception as e:
            print(f"  [research] Failed to fetch securities: {e}", flush=True)
            return

        posted = 0
        skipped = 0
        for sec in sections:
            ticker = sec["ticker"]
            sec_id = securities.get(ticker)
            if not sec_id:
                skipped += 1
                continue

            title_prefix = "Watchlist Brief" if sec["is_watchlist"] else "Research Analyst Report"
            payload = {
                "securityId": sec_id,
                "title": f"{title_prefix}: {sec['name']} ({ticker}) - {date_str}",
                "thesis": sec["body"][:60000],
                "bullCase": sec["bull_case"],
                "bearCase": sec["bear_case"],
                "baseCase": sec["base_case"],
                "moatRating": sec["moat_rating"],
                "tags": ["research-analyst", "swarm",
                         "watchlist" if sec["is_watchlist"] else "held",
                         llm_tag or get_llm_tag()],
            }

            try:
                resp = await client.post("/research/notes", json=payload)
                if resp.status_code in (200, 201):
                    posted += 1
                else:
                    print(f"  [research] Failed to post {ticker}: {resp.status_code}", flush=True)
            except Exception as e:
                print(f"  [research] Failed to post {ticker}: {e}", flush=True)

        print(f"  [research] Extracted {posted} per-security notes ({skipped} skipped)", flush=True)


# ── Technical Analyst: Per-Security Extraction ──

# Matches "### 1. TICKER — Name" (h3 headings used by technical analyst)
_TECH_SECTION_RE = re.compile(
    r"^### (\d+)\. ([A-Z][A-Z0-9._-]+) — (.+?)$",
    re.MULTILINE,
)


def _parse_technical_sections(report: str) -> list[dict]:
    """Split a technical analyst report into per-security sections."""
    matches = list(_TECH_SECTION_RE.finditer(report))
    if not matches:
        return []

    sections = []
    seen_tickers: set[str] = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        body = report[start:end].strip()
        ticker = m.group(2)
        name = m.group(3).strip()

        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)

        sections.append({
            "ticker": ticker,
            "name": name,
            "body": body,
        })

    return sections


async def extract_technical_notes(report: str, backend_url: str, date_str: str,
                                   llm_tag: str | None = None):
    """Parse technical analyst report into per-security notes and POST them."""
    sections = _parse_technical_sections(report)
    if not sections:
        print("  [technical] No per-security sections found to extract", flush=True)
        return

    async with httpx.AsyncClient(timeout=30, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        try:
            sec_resp = await client.get("/securities?limit=500")
            securities = {s["ticker"]: s["id"] for s in sec_resp.json().get("data", [])}
        except Exception as e:
            print(f"  [technical] Failed to fetch securities: {e}", flush=True)
            return

        posted = 0
        skipped = 0
        for sec in sections:
            ticker = sec["ticker"]
            sec_id = securities.get(ticker)
            if not sec_id:
                skipped += 1
                continue

            payload = {
                "securityId": sec_id,
                "title": f"Technical Analysis: {sec['name']} ({ticker}) - {date_str}",
                "thesis": sec["body"][:60000],
                "tags": ["technical-analyst", "technical", "swarm",
                         llm_tag or get_llm_tag()],
            }

            try:
                resp = await client.post("/research/notes", json=payload)
                if resp.status_code in (200, 201):
                    posted += 1
                else:
                    print(f"  [technical] Failed to post {ticker}: {resp.status_code}", flush=True)
            except Exception as e:
                print(f"  [technical] Failed to post {ticker}: {e}", flush=True)

        print(f"  [technical] Extracted {posted} per-security notes ({skipped} skipped)", flush=True)


# ── Run Single Agent ──

async def run_agent(agent_name: str, cfg: dict, date_str: str) -> str | None:
    """Run a single analyst agent."""
    backend_url = cfg["backend_url"]
    print(f"  [{agent_name}] Starting...", flush=True)
    start = time.time()

    try:
        # Load agent definition
        agent_def = load_agent_prompt(agent_name)

        # Fetch required data
        endpoints = AGENT_DATA.get(agent_name, [])
        data = await fetch_data(backend_url, endpoints)

        # For technical analyst, also fetch OHLC for holdings + watchlist securities
        if agent_name == "technical-analyst":
            try:
                sec_ids: set[int] = set()
                # Holdings
                holdings_raw = data.get("/portfolio/holdings", "[]")
                holdings = json.loads(holdings_raw) if not holdings_raw.startswith("ERROR") else []
                if isinstance(holdings, dict):
                    holdings = holdings.get("data", [])
                for h in holdings:
                    sid = h.get("securityId")
                    if sid:
                        sec_ids.add(sid)
                # Watchlist items
                wl_raw = data.get("/watchlists/items", "")
                if wl_raw and not wl_raw.startswith("ERROR"):
                    wl_items = json.loads(wl_raw).get("data", [])
                    for item in wl_items:
                        sid = item.get("securityId")
                        if sid:
                            sec_ids.add(sid)
                # Fetch OHLC for all (limit to first 40 to avoid timeout)
                for sid in list(sec_ids)[:40]:
                    extra = await fetch_data(backend_url, [f"/charts/{sid}/ohlc?period=6M&indicators=sma,ema,rsi,macd,bb"])
                    data.update(extra)
            except Exception:
                pass

        # Build prompt
        system, user_prompt = build_prompt(agent_name, agent_def, data, date_str, cfg)

        # Call LLM — research-analyst gets extra time (typically 450-570s)
        agent_timeout = 900 if agent_name == "research-analyst" else 600
        report = await call_llm(user_prompt, system, cfg, timeout=agent_timeout)

        # Store report
        await store_report(backend_url, agent_name, report)

        elapsed = round(time.time() - start, 1)
        print(f"  [{agent_name}] Complete ({elapsed}s, {len(report)} chars)", flush=True)
        return report

    except Exception as e:
        elapsed = round(time.time() - start, 1)
        print(f"  [{agent_name}] FAILED after {elapsed}s: {e}", flush=True)
        return None


# ── Per-Security Agent Execution ──

_RESEARCH_PER_SECURITY_TEMPLATE = """You are the research-analyst for the Bloomvalley investment terminal.
Analyze {ticker} ({name}) and produce your report in EXACTLY this format.
Today is {date_str}.

{data_section}

Write your analysis:

## {ticker} — {name}

**Investment Thesis**: [2-3 paragraphs covering the key investment case]

### Bull Case
[Best realistic upward scenario with target price if available]

### Bear Case
[Worst realistic downward scenario with downside target]

### Base Case
[Most likely outcome over 12 months]

**Moat Assessment**: [None/Narrow/Wide] — [one-line reasoning]
**Earnings Quality**: [High/Medium/Low/Red Flag]
**Verdict: [BUY/HOLD/SELL/WAIT/AVOID]**

Be specific with numbers. Use the data provided."""

_TECHNICAL_PER_SECURITY_TEMPLATE = """You are the technical-analyst for the Bloomvalley investment terminal.
Provide technical analysis for {ticker} ({name}). Today is {date_str}.

{data_section}

Write your analysis:

### {ticker} — {name}

**Trend**: [Bullish/Bearish/Neutral] ([timeframe])
**Key Levels**: Support [price] | Resistance [price]
**RSI**: [value] ([overbought/oversold/neutral])
**MACD**: [bullish/bearish crossover or neutral]
**Moving Averages**: [Price vs SMA50/SMA200 relationship]
**Entry Signal**: [specific price or "none"]
**Exit Signal**: [specific price or "none"]
**Confidence**: [High/Medium/Low]
**Risk/Reward**: [upside] vs [downside] = [ratio]

Be specific with price levels from the data."""


async def _post_single_research_note(
    backend_url: str, ticker: str, name: str, report: str,
    security_id: int | None, is_watchlist: bool,
    date_str: str, llm_tag: str,
):
    """Post a single per-security research note immediately after LLM completes."""
    # Resolve security ID if not provided
    if not security_id:
        async with httpx.AsyncClient(timeout=10, base_url=backend_url, headers=_AUTH_HEADERS) as client:
            resp = await client.get(f"/securities?ticker={ticker}&limit=1")
            if resp.status_code == 200:
                secs = resp.json().get("data", [])
                if secs:
                    security_id = secs[0]["id"]
    if not security_id:
        return

    # Extract structured fields
    bull = (_extract_field(report, r"### Bull [Cc]ase[^#\n]*\n(.+?)(?=\n###|\n## |\Z)")
            or _extract_field(report, r"\*\*Bull [Cc]ase[^*]*\*\*[:\s—–-]*(.+?)(?:\n\n|\n\*\*|\Z)"))
    bear = (_extract_field(report, r"### Bear [Cc]ase[^#\n]*\n(.+?)(?=\n###|\n## |\Z)")
            or _extract_field(report, r"\*\*Bear [Cc]ase[^*]*\*\*[:\s—–-]*(.+?)(?:\n\n|\n\*\*|\Z)"))
    base = (_extract_field(report, r"### Base [Cc]ase[^#\n]*\n(.+?)(?=\n###|\n## |\Z)")
            or _extract_field(report, r"\*\*Base [Cc]ase[^*]*\*\*[:\s—–-]*(.+?)(?:\n\n|\n\*\*|\Z)"))
    moat = _extract_moat(report)

    title_prefix = "Watchlist Brief" if is_watchlist else "Research Analyst Report"
    payload = {
        "securityId": security_id,
        "title": f"{title_prefix}: {name} ({ticker}) - {date_str}",
        "thesis": report[:60000],
        "bullCase": bull,
        "bearCase": bear,
        "baseCase": base,
        "moatRating": moat,
        "tags": ["research-analyst", "swarm",
                 "watchlist" if is_watchlist else "held",
                 llm_tag],
    }

    async with httpx.AsyncClient(timeout=15, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        resp = await client.post("/research/notes", json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"POST /research/notes returned {resp.status_code}")


async def run_per_security_agent(agent_name: str, cfg: dict, date_str: str) -> str | None:
    """Run research-analyst or technical-analyst with per-security LLM calls.

    Instead of one massive prompt for all securities, loops through each security
    individually with focused data and prompts. Much better for smaller models.
    """
    backend_url = cfg["backend_url"]
    per_sec_cfg = cfg.get("per_security", {})
    batch_size = per_sec_cfg.get("batch_size", 1)
    timeout_per = per_sec_cfg.get("timeout_per_call", 180)
    max_concurrent = per_sec_cfg.get("max_concurrent", 1)

    print(f"  [{agent_name}] Starting (per-security mode, batch={batch_size})...", flush=True)
    start = time.time()

    try:
        # Fetch bulk data once
        bulk_endpoints = ["/portfolio/holdings", "/fundamentals?limit=200",
                          "/insiders/signals", "/news?limit=30", "/prices/latest"]
        if agent_name == "research-analyst":
            bulk_endpoints.append("/watchlists/")
        data = await fetch_data(backend_url, bulk_endpoints)

        # Parse holdings
        holdings_raw = data.get("/portfolio/holdings", "[]")
        try:
            holdings = json.loads(holdings_raw)
            if isinstance(holdings, dict):
                holdings = holdings.get("data", [])
        except (json.JSONDecodeError, TypeError):
            holdings = []

        # Parse watchlist items
        watchlist_items = []
        wl_raw = data.get("/watchlists/items", "")
        if wl_raw and not wl_raw.startswith("ERROR"):
            try:
                watchlist_items = json.loads(wl_raw).get("data", [])
            except (json.JSONDecodeError, TypeError):
                pass

        # Build security list: held positions + watchlist batch
        securities = []
        seen_tickers = set()
        for h in holdings:
            ticker = h.get("ticker")
            if ticker and ticker not in seen_tickers:
                securities.append({
                    "ticker": ticker,
                    "name": h.get("name", ticker),
                    "securityId": h.get("securityId"),
                    "is_watchlist": False,
                })
                seen_tickers.add(ticker)

        for item in watchlist_items:
            ticker = item.get("ticker")
            if ticker and ticker not in seen_tickers:
                securities.append({
                    "ticker": ticker,
                    "name": item.get("securityName") or item.get("name", ticker),
                    "securityId": item.get("securityId"),
                    "is_watchlist": True,
                })
                seen_tickers.add(ticker)

        if not securities:
            print(f"  [{agent_name}] No securities to analyze", flush=True)
            return None

        # Select template
        is_technical = agent_name == "technical-analyst"
        template = _TECHNICAL_PER_SECURITY_TEMPLATE if is_technical else _RESEARCH_PER_SECURITY_TEMPLATE

        # For technical analyst, fetch OHLC data in bulk
        ohlc_data = {}
        if is_technical:
            for sec in securities[:40]:
                sid = sec.get("securityId")
                if sid:
                    try:
                        extra = await fetch_data(backend_url,
                                                 [f"/charts/{sid}/ohlc?period=6M&indicators=sma,ema,rsi,macd,bb"])
                        ohlc_data[sec["ticker"]] = list(extra.values())[0] if extra else ""
                    except Exception:
                        pass

        # Raw data strings for digest functions
        fundamentals_raw = data.get("/fundamentals?limit=200", "")
        insiders_raw = data.get("/insiders/signals", "")
        news_raw = data.get("/news?limit=30", "")

        # Report initial status
        total_sec = len(securities)
        completed_sec = 0
        await report_status(backend_url, "running", agent=agent_name,
                            completed=0, total=total_sec,
                            message=f"Analyzing {total_sec} securities")

        # Process securities
        semaphore = asyncio.Semaphore(max_concurrent)
        all_reports = []

        async def analyze_security(n: int, sec: dict) -> str | None:
            nonlocal completed_sec
            ticker = sec["ticker"]
            name = sec["name"]
            prefix = "W-" if sec["is_watchlist"] else ""

            # Build per-security data section
            if is_technical:
                ohlc_raw = ohlc_data.get(ticker, "")
                data_section = digest_technical(ohlc_raw, ticker)
            else:
                parts = []
                fund_text = digest_fundamentals_for_security(fundamentals_raw, ticker)
                if fund_text:
                    parts.append(fund_text)
                insider_text = digest_insider_signals(insiders_raw, ticker)
                if insider_text and "No insider" not in insider_text:
                    parts.append(insider_text)
                news_text = digest_news(news_raw, ticker)
                if news_text and "No recent" not in news_text:
                    parts.append(news_text)
                data_section = "\n\n".join(parts) if parts else f"Limited data available for {ticker}."

            # Build prompt from template
            prompt = template.format(
                ticker=ticker, name=name, date_str=date_str,
                n=f"{prefix}{n}", data_section=data_section,
            )

            async with semaphore:
                try:
                    report = await call_llm(prompt, "", cfg, timeout=timeout_per)
                    # Strip stray fundamentals blocks for other tickers
                    # (LLM sometimes echoes data from context/training)
                    report = _strip_foreign_fundamentals(report, ticker)

                    # Post per-security note immediately (don't wait for all to finish)
                    if report and agent_name == "research-analyst":
                        try:
                            await _post_single_research_note(
                                backend_url, ticker, name, report,
                                sec.get("securityId"), sec["is_watchlist"],
                                date_str, get_llm_tag(),
                            )
                            print(f"  [{agent_name}] {prefix}{n}/{len(securities)} {ticker} ✓ (posted)", flush=True)
                        except Exception as e:
                            print(f"  [{agent_name}] {prefix}{n}/{len(securities)} {ticker} ✓ (note post failed: {e})", flush=True)
                    else:
                        print(f"  [{agent_name}] {prefix}{n}/{len(securities)} {ticker} ✓", flush=True)

                    completed_sec += 1
                    await report_status(backend_url, "running", agent=agent_name,
                                        completed=completed_sec, total=total_sec,
                                        message=f"{ticker} done ({completed_sec}/{total_sec})")
                    return report
                except Exception as e:
                    completed_sec += 1
                    await report_status(backend_url, "running", agent=agent_name,
                                        completed=completed_sec, total=total_sec,
                                        message=f"{ticker} failed ({completed_sec}/{total_sec})")
                    print(f"  [{agent_name}] {prefix}{n}/{len(securities)} {ticker} ✗ {e}", flush=True)
                    return None

        # Run all securities (batch_size controls how many in parallel)
        tasks = [analyze_security(i + 1, sec) for i, sec in enumerate(securities)]
        results = await asyncio.gather(*tasks)

        # Collect successful reports
        posted = 0
        for sec, report in zip(securities, results):
            if report:
                all_reports.append(report)
                posted += 1

        # Concatenate into combined report
        combined = "\n\n---\n\n".join(all_reports)

        # Store combined report
        await store_report(backend_url, agent_name, combined)

        elapsed = round(time.time() - start, 1)
        print(f"  [{agent_name}] Complete ({elapsed}s, {len(combined)} chars, "
              f"{posted}/{len(securities)} securities)", flush=True)
        return combined

    except Exception as e:
        elapsed = round(time.time() - start, 1)
        print(f"  [{agent_name}] FAILED after {elapsed}s: {e}", flush=True)
        traceback.print_exc()
        return None


# ── Deployment Plan: Auto-track Progress ──


async def update_deployment_progress(backend_url: str):
    """Compare buy transactions against active deployment plan and update progress.

    Each tranche counts only buy transactions within its date window:
    tranche start = its plannedDate (or plan startDate for the first tranche)
    tranche end = next tranche's plannedDate (or plan endDate for the last)
    """
    async with httpx.AsyncClient(timeout=30, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        try:
            # Get active deployment plan
            resp = await client.get("/deployment-plans/current")
            if resp.status_code != 200:
                return
            plan = resp.json().get("data", {})
            plan_id = plan.get("id")
            if not plan_id:
                return

            tranches = plan.get("tranches", [])
            if not tranches:
                return

            # Get FX rates for currency conversion
            fx_resp = await client.get("/prices/fx-rates")
            fx_rates = {}
            if fx_resp.status_code == 200:
                for r in fx_resp.json().get("data", []):
                    fx_rates[r.get("currency", r.get("quoteCurrency", ""))] = r.get("rate", 1)

            # Fetch all buy transactions since plan start
            tx_resp = await client.get("/transactions?type=buy&limit=500")
            if tx_resp.status_code != 200:
                return
            all_buys = tx_resp.json().get("data", [])

            plan_start = plan.get("startDate", "")
            plan_end = plan.get("endDate", "9999-12-31")

            # Sort tranches by planned date
            sorted_tranches = sorted(tranches, key=lambda t: t.get("plannedDate", ""))

            for i, tranche in enumerate(sorted_tranches):
                tranche_id = tranche["id"]
                target_cents = tranche.get("amountCents", 0)

                # Determine this tranche's date window
                # First tranche starts at plan start, others at their own planned date
                window_start = plan_start if i == 0 else tranche.get("plannedDate", plan_start)

                # Ends at next tranche's planned date, or plan end for the last
                if i + 1 < len(sorted_tranches):
                    window_end = sorted_tranches[i + 1].get("plannedDate", plan_end)
                else:
                    window_end = plan_end

                # Sum buys within this tranche's window
                tranche_deployed = 0
                notes_parts = []

                for tx in all_buys:
                    trade_date = tx.get("tradeDate", "")
                    if trade_date < window_start or trade_date >= window_end:
                        continue

                    total_cents = tx.get("totalCents", 0)
                    currency = tx.get("currency", "EUR")

                    if currency == "EUR":
                        eur_cents = total_cents
                    else:
                        fx = fx_rates.get(currency, 1)
                        eur_cents = int(total_cents / fx) if fx else total_cents

                    tranche_deployed += eur_cents
                    ticker = tx.get("ticker", "?")
                    notes_parts.append(f"{trade_date}: {ticker} {eur_cents/100:.0f}EUR")

                # Determine status
                if tranche_deployed >= target_cents:
                    status = "completed"
                elif tranche_deployed > 0:
                    status = "in_progress"
                else:
                    status = "pending"

                notes = "; ".join(notes_parts[-10:]) if notes_parts else None

                # Only update if there's a change
                old_status = tranche.get("status")
                old_amount = tranche.get("executedAmountCents", 0)
                if status != old_status or tranche_deployed != old_amount:
                    payload = {
                        "status": status,
                        "executedAmountCents": tranche_deployed,
                    }
                    if notes is not None:
                        payload["executionNotes"] = notes

                    await client.put(
                        f"/deployment-plans/{plan_id}/tranches/{tranche_id}",
                        json=payload,
                    )
                    print(f"  [deployment] Tranche {tranche['quarterLabel']}: "
                          f"€{tranche_deployed/100:,.0f}/€{target_cents/100:,.0f} ({status})",
                          flush=True)

        except Exception as e:
            print(f"  [deployment] Failed to update progress: {e}", flush=True)


# ── Portfolio Manager: Close Old Recs + Post New ──

async def close_old_recommendations(backend_url: str):
    """Close all active recommendations before posting new ones."""
    async with httpx.AsyncClient(timeout=30, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        try:
            resp = await client.get("/recommendations?status=active&limit=200")
            if resp.status_code == 200:
                recs = resp.json().get("data", [])
                for r in recs:
                    await client.put(f"/recommendations/{r['id']}/close", json={
                        "outcome_notes": "Closed by analyst swarm — new analysis generated"
                    })
                print(f"  [pm] Closed {len(recs)} old recommendations", flush=True)
        except Exception as e:
            print(f"  [pm] Failed to close old recommendations: {e}", flush=True)


MORNING_BRIEF_PROMPT = """Summarize this portfolio manager report for a Telegram morning brief in 3000-4500 characters.
Structure:
1. Macro outlook (2-3 lines — regime, key risks, tailwinds, rate environment)
2. Key news & catalysts (3-5 lines — most impactful headlines, events, earnings, policy changes)
3. BUY recommendations — each ticker with 1-2 sentence rationale
4. SELL recommendations — each ticker with reason
5. Notable HOLDs — highlight any with significant news, upcoming dividends, or changed thesis (skip routine holds)
6. WAIT/watchlist — tickers worth monitoring with trigger conditions
7. Portfolio risk summary (1-2 lines — concentration, sector exposure, key risks to monitor)
Keep it dense and actionable. No greetings, no HTML tags, plain text only. Do NOT include any monetary values, position sizes, or portfolio amounts."""

MIDDAY_UPDATE_PROMPT = """You are comparing the MORNING portfolio manager brief with the latest NOON analysis.

MORNING BRIEF:
{morning_summary}

CURRENT (NOON) REPORT:
{current_report}

Write a mid-day changes update for Telegram in 2000-3500 characters. Focus ONLY on what changed since the morning:
1. New or changed recommendations (upgrades, downgrades, new BUY/SELL actions not in morning)
2. Recommendation changes (any ticker whose action or confidence changed since morning)
3. Significant market moves or news that emerged since the morning brief
4. Removed recommendations (tickers in morning brief no longer recommended)
5. Changed macro outlook (only if it shifted since morning)
If nothing material changed, say so briefly — "No material changes since morning brief" with a 1-2 line market color.
Keep it dense and actionable. No greetings, no HTML tags, plain text only. Do NOT include any monetary values, position sizes, or portfolio amounts."""

EVENING_BRIEF_PROMPT = """Summarize this portfolio manager report as an evening wrap-up for Telegram in 3000-4500 characters.
This is the final brief of the day. Structure it as:
1. Day in review (3-5 lines — what happened in markets today, major moves, news impact)
2. Recommendation changes today (what changed across all runs — new positions, closed positions, upgrades/downgrades)
3. Key earnings/events ahead (upcoming catalysts in next 1-2 days)
4. Overnight/tomorrow watch (what to monitor — Asian markets, futures, data releases)
5. Forward outlook (2-3 lines — positioning thoughts for tomorrow and the week ahead)
Keep it dense and forward-looking. No greetings, no HTML tags, plain text only. Do NOT include any monetary values, position sizes, or portfolio amounts."""

WEEKEND_MACRO_PROMPT = """Summarize this portfolio manager report as a weekend macro overview for Telegram in 3000-4500 characters.
Markets are closed — focus on the bigger picture, not intraday moves. Structure it as:
1. Weekly macro recap (3-5 lines — key economic data, central bank moves, geopolitical shifts from the past week)
2. Sector & industry impact (5-8 lines — which industries are most affected by this week's macro developments, why, and the direction of impact)
3. Shares to watch (list tickers with 1-2 sentence rationale — securities in the portfolio or watchlist most exposed to the macro trends above, both positively and negatively)
4. Week ahead preview (3-5 lines — upcoming data releases, earnings, central bank meetings, events that could move markets Monday)
5. Positioning thoughts (2-3 lines — any rebalancing or readiness ideas heading into the new week)
Keep it analytical and forward-looking. No greetings, no HTML tags, plain text only. Do NOT include any monetary values, position sizes, or portfolio amounts."""

# Map brief types to prompts (morning is the default/fallback)
_BRIEF_PROMPTS = {
    "morning": MORNING_BRIEF_PROMPT,
    "evening": EVENING_BRIEF_PROMPT,
    "weekend": WEEKEND_MACRO_PROMPT,
}

# Legacy alias
SUMMARIZE_PM_PROMPT = MORNING_BRIEF_PROMPT


EXTRACT_RECS_PROMPT = """Extract ALL actionable recommendations from this portfolio manager report.
Return a JSON array of objects. Each object must have these fields:
- "ticker": string (e.g. "VWCE", "ALYK", "MSFT", "INVE-B.ST", "KESKOB.HE")
- "action": "buy" | "sell" | "hold" | "wait"
- "confidence": "high" | "medium" | "low"
- "rationale": string (1-3 sentence summary of the recommendation)
- "bull_case": string (REQUIRED — what could go right, never null)
- "bear_case": string (REQUIRED — what could go wrong, never null)
- "time_horizon": "short" | "medium" | "long" (short=<3m, medium=3-12m, long=>12m)

IMPORTANT action rules:
- Use "hold" ONLY for securities the investor currently owns (held positions).
- Use "wait" for watchlist securities the investor does NOT own but should keep watching.
- Use "buy" for securities the investor should purchase (whether held or watchlist).
- Use "sell" for securities the investor should sell (must be held).
- Never use "hold" for a security the investor doesn't own.

Include ALL recommendations from the report, including hold and wait recommendations.
For "sell" actions on funds being redeemed, use "sell".
Return ONLY the JSON array, no markdown fences, no explanation."""


async def extract_and_post_recommendations(report: str, cfg: dict, date_str: str,
                                            brief_type: str = "morning"):
    """Parse the PM report into structured recommendations and POST them."""
    backend_url = cfg["backend_url"]
    print(f"  [pm] Extracting recommendations from report (brief={brief_type})...", flush=True)

    try:
        # Try to parse structured JSON block from PM output directly (avoids second LLM call)
        recs = None
        json_match = re.search(r'```json\s*\n(\[[\s\S]*?\])\s*\n```', report)
        if json_match:
            try:
                recs = json.loads(json_match.group(1))
                if isinstance(recs, list) and len(recs) > 0:
                    print(f"  [pm] Parsed {len(recs)} recommendations from JSON block", flush=True)
                else:
                    recs = None
            except (json.JSONDecodeError, TypeError):
                recs = None

        # Fallback: use second LLM call to extract recommendations
        if recs is None:
            print("  [pm] No JSON block found, using LLM extraction fallback...", flush=True)
            result = await call_llm(
                f"Portfolio manager report:\n\n{report}",
                EXTRACT_RECS_PROMPT,
                cfg,
            )

            # Parse JSON — handle markdown fences if present
            text = result.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            recs = json.loads(text)
            if not isinstance(recs, list):
                print("  [pm] LLM did not return a JSON array", flush=True)
                return

        # Resolve tickers to security IDs
        async with httpx.AsyncClient(timeout=30, base_url=backend_url, headers=_AUTH_HEADERS) as client:
            sec_resp = await client.get("/securities?limit=500")
            securities = {s["ticker"]: s["id"] for s in sec_resp.json().get("data", [])}

            posted = 0
            for rec in recs:
                ticker = rec.get("ticker", "")
                sec_id = securities.get(ticker)
                if not sec_id:
                    print(f"  [pm] Skipping {ticker} — not found in securities", flush=True)
                    continue

                payload = {
                    "security_id": sec_id,
                    "action": rec.get("action", "hold"),
                    "confidence": rec.get("confidence", "medium"),
                    "rationale": rec.get("rationale", ""),
                    "bull_case": rec.get("bull_case"),
                    "bear_case": rec.get("bear_case"),
                    "source": "portfolio-manager",
                    "time_horizon": rec.get("time_horizon", "medium"),
                    "recommended_date": date_str,
                }

                resp = await client.post("/recommendations", json=payload)
                if resp.status_code in (200, 201):
                    posted += 1
                else:
                    print(f"  [pm] Failed to post {ticker}: {resp.status_code}", flush=True)

            print(f"  [pm] Posted {posted} recommendations", flush=True)

            # Notify via Telegram — brief type determines the summary style
            # Weekend: only morning run sends Telegram (macro overview), skip midday/evening
            if posted > 0:
                from zoneinfo import ZoneInfo
                is_weekend = datetime.now(ZoneInfo("Europe/Helsinki")).weekday() >= 5

                if is_weekend and brief_type != "morning":
                    print(f"  [pm] Weekend — skipping {brief_type} Telegram notification", flush=True)
                elif is_weekend:
                    # Weekend morning — send macro overview instead of regular brief
                    try:
                        summary = await call_llm(
                            f"Portfolio manager report:\n\n{report}",
                            WEEKEND_MACRO_PROMPT,
                            cfg,
                        )
                        await client.post("/notifications/send", json={
                            "event": "recommendations",
                            "data": {
                                "summary": summary[:4800],
                                "date": date_str,
                                "brief_type": "weekend",
                            },
                        })
                    except Exception:
                        pass  # Non-critical
                else:
                    # Weekday — normal brief flow
                    try:
                        if brief_type == "midday":
                            # Fetch morning brief from backend for diffing
                            morning_summary = ""
                            try:
                                ms_resp = await client.get(
                                    f"/notifications/brief-summary/{date_str}/morning"
                                )
                                if ms_resp.status_code == 200:
                                    morning_summary = ms_resp.json().get("data", {}).get("summary", "")
                            except Exception:
                                pass

                            if morning_summary:
                                prompt = MIDDAY_UPDATE_PROMPT.format(
                                    morning_summary=morning_summary,
                                    current_report=report,
                                )
                                summary = await call_llm(
                                    "Generate the mid-day changes update.",
                                    prompt,
                                    cfg,
                                )
                            else:
                                # No morning brief available — fall back to full summary
                                print("  [pm] No morning brief found, using full summary", flush=True)
                                summary = await call_llm(
                                    f"Portfolio manager report:\n\n{report}",
                                    MORNING_BRIEF_PROMPT,
                                    cfg,
                                )
                                brief_type = "morning"  # label it correctly
                        else:
                            # Morning or evening — use the appropriate prompt
                            prompt = _BRIEF_PROMPTS.get(brief_type, MORNING_BRIEF_PROMPT)
                            summary = await call_llm(
                                f"Portfolio manager report:\n\n{report}",
                                prompt,
                                cfg,
                            )

                        await client.post("/notifications/send", json={
                            "event": "recommendations",
                            "data": {
                                "summary": summary[:4800],
                                "date": date_str,
                                "brief_type": brief_type,
                            },
                        })
                    except Exception:
                        pass  # Non-critical

    except Exception as e:
        print(f"  [pm] Failed to extract recommendations: {e}", flush=True)


# ── Phased Portfolio Manager ──


def _build_pm_data_brief(data: dict[str, str], date_str: str) -> str:
    """Phase 1: Deterministic extraction of factual data into clean text.

    Extracts dividends, no-trade windows, position summaries, and macro data
    from raw API responses using Python — no LLM needed.  This eliminates
    the TBD/hallucination problem.
    """
    sections = []

    # ── Dividend Calendar ──
    div_raw = data.get("/dividends/upcoming", "")
    if div_raw and not div_raw.startswith("ERROR"):
        try:
            div_data = json.loads(div_raw)
            items = div_data.get("data", div_data) if isinstance(div_data, dict) else div_data
            if items:
                lines = ["## DIVIDEND CALENDAR"]
                lines.append("| Ticker | Ex-Date | Amount/Share | Currency | Shares Held | Total (EUR) | Projected |")
                lines.append("|--------|---------|-------------|----------|-------------|-------------|-----------|")
                for d in items:
                    per_share = d.get("amountPerShareCents")
                    ps_str = f"{per_share / 100:.2f}" if per_share else "?"
                    total_eur = d.get("totalEurCents")
                    te_str = f"€{total_eur / 100:.2f}" if total_eur else "?"
                    lines.append(
                        f"| {d.get('ticker', '?')} | {d.get('exDate', '?')} | {ps_str} | "
                        f"{d.get('currency', '?')} | {d.get('sharesHeld', '?')} | {te_str} | "
                        f"{'Yes' if d.get('projected') else 'No'} |"
                    )
                sections.append("\n".join(lines))
        except (json.JSONDecodeError, TypeError):
            sections.append("## DIVIDEND CALENDAR\nData unavailable.")
    else:
        sections.append("## DIVIDEND CALENDAR\nData unavailable.")

    # ── 30-Day No-Trade Windows (from buy transactions only) ──
    buy_raw = data.get("/transactions?type=buy&limit=50", "")
    if buy_raw and not buy_raw.startswith("ERROR"):
        try:
            buy_data = json.loads(buy_raw)
            items = buy_data.get("data", buy_data) if isinstance(buy_data, dict) else buy_data
            from datetime import datetime as dt, timedelta
            cutoff = dt.strptime(date_str, "%Y-%m-%d") - timedelta(days=30)
            recent_buys = {}
            for t in items:
                trade_date_str = t.get("tradeDate") or t.get("date")
                if not trade_date_str:
                    continue
                trade_date = dt.strptime(trade_date_str[:10], "%Y-%m-%d")
                if trade_date >= cutoff:
                    ticker = t.get("ticker", "?")
                    if ticker not in recent_buys or trade_date > dt.strptime(recent_buys[ticker]["date"], "%Y-%m-%d"):
                        days_ago = (dt.strptime(date_str, "%Y-%m-%d") - trade_date).days
                        recent_buys[ticker] = {"date": trade_date_str[:10], "days_ago": days_ago}
            lines = ["## 30-DAY NO-TRADE WINDOWS"]
            if recent_buys:
                lines.append("These tickers have BUY transactions within the last 30 days — bias toward HOLD:")
                for ticker, info in sorted(recent_buys.items()):
                    remaining = 30 - info["days_ago"]
                    lines.append(f"  - {ticker}: last buy {info['date']} ({info['days_ago']}d ago, {remaining}d remaining)")
            else:
                lines.append("No tickers have buy transactions within the last 30 days. All positions are clear for trading.")
            sections.append("\n".join(lines))
        except (json.JSONDecodeError, TypeError):
            sections.append("## 30-DAY NO-TRADE WINDOWS\nBuy transaction data unavailable — cannot determine windows.")
    else:
        sections.append("## 30-DAY NO-TRADE WINDOWS\nBuy transaction data unavailable — cannot determine windows.")

    # ── Position Summary (top holdings with key metrics) ──
    holdings_raw = data.get("/portfolio/holdings", "")
    fundamentals_raw = data.get("/fundamentals?limit=200", "")
    if holdings_raw and not holdings_raw.startswith("ERROR"):
        try:
            h_data = json.loads(holdings_raw)
            holdings = h_data.get("data", h_data) if isinstance(h_data, dict) else h_data
            # Parse fundamentals for metrics
            fund_map = {}
            if fundamentals_raw and not fundamentals_raw.startswith("ERROR"):
                f_data = json.loads(fundamentals_raw)
                f_items = f_data.get("data", f_data) if isinstance(f_data, dict) else f_data
                for f in f_items:
                    sid = f.get("securityId")
                    if sid:
                        fund_map[sid] = f

            # Deduplicate by ticker, sum values across accounts
            by_ticker = {}
            for h in holdings:
                ticker = h.get("ticker", "?")
                if ticker not in by_ticker:
                    by_ticker[ticker] = {
                        "name": h.get("name", "?"),
                        "securityId": h.get("securityId"),
                        "assetClass": h.get("assetClass", "?"),
                        "sector": h.get("sector", ""),
                        "valueCents": 0,
                        "pnlPct": h.get("unrealizedPnlPct"),
                    }
                by_ticker[ticker]["valueCents"] += h.get("marketValueEurCents") or 0

            # Sort by value descending
            sorted_holdings = sorted(by_ticker.items(), key=lambda x: x[1]["valueCents"], reverse=True)
            total_val = sum(v["valueCents"] for _, v in sorted_holdings) or 1

            lines = ["## HELD POSITIONS"]
            lines.append("| # | Ticker | Name | Weight | Value (EUR) | P&L | ROIC | P/E | Div Yield | Sector |")
            lines.append("|---|--------|------|--------|-------------|-----|------|-----|-----------|--------|")
            for i, (ticker, h) in enumerate(sorted_holdings, 1):
                weight = h["valueCents"] / total_val * 100
                value_str = f"€{h['valueCents'] / 100:,.0f}"
                pnl_str = f"{h['pnlPct']:.1f}%" if h.get("pnlPct") is not None else "?"
                f = fund_map.get(h["securityId"], {})
                roic = f.get("roic")
                roic_str = f"{float(roic)*100:.1f}%" if roic else "-"
                pe = f.get("peRatio")
                pe_str = f"{float(pe):.1f}" if pe else "-"
                div_y = f.get("dividendYield")
                div_str = f"{float(div_y)*100:.1f}%" if div_y else "-"
                lines.append(
                    f"| {i} | {ticker} | {h['name'][:25]} | {weight:.1f}% | {value_str} | "
                    f"{pnl_str} | {roic_str} | {pe_str} | {div_str} | {h.get('sector', '-')[:15]} |"
                )
            sections.append("\n".join(lines))
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Portfolio Summary ──
    summary_raw = data.get("/portfolio/summary", "")
    if summary_raw and not summary_raw.startswith("ERROR"):
        try:
            s_data = json.loads(summary_raw)
            s = s_data.get("data", s_data) if isinstance(s_data, dict) else s_data
            lines = ["## PORTFOLIO SUMMARY"]
            lines.append(f"- Total Value: €{s.get('totalValueEurCents', 0) / 100:,.2f}")
            lines.append(f"- Cost Basis: €{s.get('totalCostEurCents', 0) / 100:,.2f}")
            lines.append(f"- Cash: €{s.get('totalCashEurCents', 0) / 100:,.2f}")
            lines.append(f"- Unrealized P&L: €{s.get('unrealizedPnlCents', 0) / 100:,.2f}"
                         f" ({s.get('unrealizedPnlPct', 0):.1f}%)" if s.get("unrealizedPnlPct") else "")
            lines.append(f"- Holdings: {s.get('holdingsCount', '?')}")
            alloc = s.get("allocation", {})
            if alloc:
                total = sum(alloc.values()) or 1
                lines.append("- Allocation: " + ", ".join(
                    f"{k} {v/total*100:.0f}%" for k, v in sorted(alloc.items(), key=lambda x: -x[1])
                ))
            sections.append("\n".join(lines))
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Macro Regime ──
    regime_raw = data.get("/macro/regime", "")
    if regime_raw and not regime_raw.startswith("ERROR"):
        try:
            r_data = json.loads(regime_raw)
            regime = r_data.get("data", r_data) if isinstance(r_data, dict) else r_data
            if isinstance(regime, dict):
                lines = ["## MACRO REGIME"]
                lines.append(f"Regime: **{regime.get('regime', '?')}** (confidence: {regime.get('confidence', '?')}, score: {regime.get('compositeScore', '?')})")
                for sig in regime.get("signals", []):
                    lines.append(f"  - {sig.get('name')}: {sig.get('signal')} — {sig.get('detail', '')}")
                sections.append("\n".join(lines))
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Macro Indicators (with staleness annotation) ──
    summary_macro_raw = data.get("/macro/summary", "")
    if summary_macro_raw and not summary_macro_raw.startswith("ERROR"):
        try:
            from datetime import datetime as dt
            today = dt.strptime(date_str, "%Y-%m-%d")
            sm_data = json.loads(summary_macro_raw)
            regions = sm_data.get("data", sm_data) if isinstance(sm_data, dict) else sm_data
            if isinstance(regions, list):
                lines = ["## MACRO INDICATORS"]
                lines.append("Each indicator includes its release date and staleness. Only flag as 'CHANGED' if the data point is ≤14 days old.")
                lines.append("")
                for region in regions:
                    lines.append(f"### {region.get('regionLabel', '?')}")
                    for cat in region.get("categories", []):
                        for ind in cat.get("indicators", []):
                            name = ind.get("name", "?")
                            value = ind.get("value")
                            unit = ind.get("unit", "")
                            ind_date = ind.get("date", "")
                            change = ind.get("change")
                            freq = ind.get("frequency", "")

                            # Compute staleness
                            staleness = ""
                            if ind_date:
                                try:
                                    d = dt.strptime(ind_date[:10], "%Y-%m-%d")
                                    days_old = (today - d).days
                                    if days_old <= 1:
                                        staleness = "TODAY"
                                    elif days_old <= 7:
                                        staleness = f"CHANGED {days_old}d ago"
                                    elif days_old <= 14:
                                        staleness = f"recent ({days_old}d ago)"
                                    else:
                                        staleness = f"as of {ind_date[:10]} ({days_old}d ago)"
                                except ValueError:
                                    staleness = f"date: {ind_date}"

                            # Format value
                            if value is not None:
                                if unit == "%":
                                    val_str = f"{value}{unit}"
                                elif unit and "EUR" in unit:
                                    val_str = f"€{value:,.0f}{unit.replace('EUR','').replace('M',' M')}"
                                else:
                                    val_str = f"{value} {unit}".strip()
                            else:
                                val_str = "N/A"

                            # Format change
                            chg_str = ""
                            if change is not None and change != 0:
                                sign = "+" if change > 0 else ""
                                if unit == "%":
                                    chg_str = f" ({sign}{change}pp)"
                                elif "bps" in str(unit).lower():
                                    chg_str = f" ({sign}{change}bps)"
                                else:
                                    chg_str = f" ({sign}{change})"

                            lines.append(f"  - {name}: **{val_str}**{chg_str} [{staleness}] ({freq})")
                    lines.append("")
                sections.append("\n".join(lines))
        except (json.JSONDecodeError, TypeError):
            pass

    return "\n\n".join(sections)


def _extract_analyst_verdicts(data: dict[str, str]) -> str:
    """Extract per-security analyst verdicts from research notes."""
    raw = data.get("/research/notes?tag=research-analyst&limit=100", "")
    if not raw or raw.startswith("ERROR"):
        return ""

    try:
        notes_data = json.loads(raw)
        notes = notes_data.get("data", notes_data) if isinstance(notes_data, dict) else notes_data
    except (json.JSONDecodeError, TypeError):
        return ""

    if not notes:
        return ""

    lines = ["## ANALYST VERDICTS (from research-analyst notes)"]
    for note in notes[:60]:
        title = note.get("title", "")
        ticker = ""
        # Extract ticker from title like "Research Analyst Report: KESKOB.HE - 2026-04-09"
        if ":" in title:
            parts = title.split(":")
            if len(parts) >= 2:
                ticker_part = parts[1].strip().split(" - ")[0].strip()
                if ticker_part:
                    ticker = ticker_part

        # Extract verdict from thesis
        thesis = note.get("thesis", "")[:500]
        verdict_match = re.search(
            r"\*\*(?:Verdict[:\s]*)?(?:\*\*)?\s*(BUY|SELL|HOLD|WAIT|AVOID|ACCUMULATE|TRIM)\b",
            thesis, re.IGNORECASE,
        )
        verdict = verdict_match.group(1).upper() if verdict_match else "?"
        moat = note.get("moatRating", "?")

        # Get bull/bear one-liners
        bull = (note.get("bullCase") or "")[:120]
        bear = (note.get("bearCase") or "")[:120]

        if ticker:
            line = f"  - **{ticker}**: {verdict} (moat: {moat})"
            if bull:
                line += f" | Bull: {bull}"
            if bear:
                line += f" | Bear: {bear}"
            lines.append(line)

    return "\n".join(lines) if len(lines) > 1 else ""


async def run_portfolio_manager_phased(cfg: dict, date_str: str) -> str | None:
    """Run the portfolio manager in structured phases.

    Phase 1 (Python): Deterministic data extraction into clean text
    Phase 2 (LLM): Holdings analysis — recommendations for held positions
    Phase 3 (LLM): Watchlist opportunities — best buys from watchlists
    Phase 4 (LLM): Final synthesis — combine into standard PM report format
    """
    backend_url = cfg["backend_url"]
    print("  [portfolio-manager] Starting (phased mode)...", flush=True)
    start = time.time()

    try:
        # Load agent definition
        agent_def = load_agent_prompt("portfolio-manager")

        # Fetch all PM data
        endpoints = AGENT_DATA.get("portfolio-manager", [])
        data = await fetch_data(backend_url, endpoints)

        # Phase 1: Deterministic data extraction
        print("  [pm] Phase 1: Extracting data brief...", flush=True)
        data_brief = _build_pm_data_brief(data, date_str)
        analyst_verdicts = _extract_analyst_verdicts(data)

        # Build remaining data sections (digest non-factual data for LLM)
        use_digest = cfg.get("digest_data", False)
        factual_endpoints = {
            "/dividends/upcoming", "/transactions?type=buy&limit=50",
            "/portfolio/holdings", "/portfolio/summary", "/fundamentals?limit=200",
            "/macro/regime", "/macro/summary",
        }
        remaining_data = {k: v for k, v in data.items() if k not in factual_endpoints}

        if use_digest:
            from data_digest import auto_digest
            digested = auto_digest(remaining_data)
            other_data_section = "\n\n".join(
                f"### {label}\n{content}" for label, content in digested.items() if content
            )
        else:
            other_data_section = "\n\n".join(
                f"### Data from {ep}\n```json\n{content[:10000]}\n```"
                if not content.startswith("ERROR")
                else f"### Data from {ep}\n*Unavailable: {content}*"
                for ep, content in remaining_data.items()
            )

        # Phase 2: Holdings analysis
        print("  [pm] Phase 2: Analyzing held positions...", flush=True)
        holdings_system = f"""You are the portfolio-manager for the Bloomvalley investment terminal.
Today is {date_str}. Analyze each held position and provide a recommendation.
ALL data has been pre-extracted below — do NOT attempt to make API calls."""

        holdings_prompt = f"""# Task
Analyze each held position and provide a BUY/HOLD/SELL/TRIM recommendation with rationale.

# Pre-Extracted Data

{data_brief}

{analyst_verdicts}

# Other Analyst Reports

{other_data_section}

# Instructions

For EACH held position in the table above, provide:
1. **Action** (BUY more / HOLD / SELL / TRIM) with confidence (high/medium/low)
2. **One-line rationale** — why this action now
3. **Key signals** — ROIC, valuation, insider activity, macro alignment
4. Use the 30-DAY NO-TRADE WINDOWS section above — only flag tickers listed there. If a ticker is NOT listed, it has NO window.
5. Use the DIVIDEND CALENDAR above — include exact EUR amounts from the table, never write TBD.
6. Flag positions >10% weight as concentration risk.
7. Flag positions <€200 as dust (do not recommend selling).

Be concise — one paragraph per position. Output as a numbered list."""

        holdings_analysis = await call_llm(holdings_prompt, holdings_system, cfg, timeout=600)

        # Phase 3: Watchlist opportunities
        print("  [pm] Phase 3: Evaluating watchlist opportunities...", flush=True)
        watchlist_system = f"""You are the portfolio-manager for the Bloomvalley investment terminal.
Today is {date_str}. Identify the best BUY opportunities from watchlist securities.
ALL data has been pre-extracted below — do NOT attempt to make API calls."""

        # Get watchlist data
        wl_data_parts = []
        for k, v in data.items():
            if "watchlist" in k.lower() or "screener" in k.lower():
                if not v.startswith("ERROR"):
                    if use_digest:
                        from data_digest import auto_digest
                        d = auto_digest({k: v})
                        for label, content in d.items():
                            if content:
                                wl_data_parts.append(f"### {label}\n{content}")
                    else:
                        wl_data_parts.append(f"### {k}\n```json\n{v[:10000]}\n```")

        watchlist_prompt = f"""# Task
Identify the top 5-10 BUY opportunities from watchlist securities that the investor does NOT currently own.

# Watchlist Data

{chr(10).join(wl_data_parts) if wl_data_parts else "No watchlist data available."}

{analyst_verdicts}

# Instructions

For each recommendation:
1. **Ticker + Name**
2. **Why now** — catalyst, valuation, quality metrics
3. **Position size** — suggested EUR amount and share count
4. **Risk** — key downside risk
5. Use "buy" for securities ready to purchase, "wait" for those to keep watching.
6. Never use "hold" for securities the investor doesn't own.

Output as a numbered list, ranked by conviction."""

        watchlist_analysis = await call_llm(watchlist_prompt, watchlist_system, cfg, timeout=300)

        # Phase 4: Final synthesis
        print("  [pm] Phase 4: Synthesizing final report...", flush=True)
        synthesis_system = f"""You are the portfolio-manager for the Bloomvalley investment terminal.
Today is {date_str}. Synthesize the analysis below into your final report.
ALL data and analysis has been provided — do NOT attempt to make API calls."""

        synthesis_prompt = f"""# Agent Definition

{agent_def}

# Pre-Extracted Factual Data (use these numbers exactly — never write TBD)

{data_brief}

# Holdings Analysis (Phase 2)

{holdings_analysis}

# Watchlist Opportunities (Phase 3)

{watchlist_analysis}

# Remaining Data

{other_data_section}

# Instructions

Produce your COMPLETE final report following the exact format in your agent definition:
0. EXECUTIVE SUMMARY
1. MACRO paragraph
2. THIS WEEK section (use DIVIDEND CALENDAR data above — include exact EUR amounts)
3. Rebalancing Recommendations (combine holdings + watchlist analysis)
4. Risk Exposure Summary
5. DEPLOYMENT PLAN STATUS

Then output the structured JSON recommendations block.

CRITICAL RULES:
- Use the exact dividend amounts from the DIVIDEND CALENDAR table above. Never write "TBD".
- Use the 30-DAY NO-TRADE WINDOWS section above. Only flag tickers listed there. If a ticker is NOT listed, there is NO window.
- Use "hold" only for held positions, "wait" for watchlist securities not owned.
- Include bull AND bear case for every BUY or SELL."""

        final_report = await call_llm(synthesis_prompt, synthesis_system, cfg, timeout=900)

        # Store the full report
        await store_report(backend_url, "portfolio-manager", final_report)

        elapsed = round(time.time() - start, 1)
        print(f"  [portfolio-manager] Complete ({elapsed}s, {len(final_report)} chars, 4 phases)", flush=True)
        return final_report

    except Exception as e:
        elapsed = round(time.time() - start, 1)
        print(f"  [portfolio-manager] FAILED after {elapsed}s: {e}", flush=True)
        traceback.print_exc()
        return None


# ── Main Swarm Run ──

def _detect_brief_type() -> str:
    """Determine brief type based on current Helsinki time."""
    from zoneinfo import ZoneInfo
    hour = datetime.now(ZoneInfo("Europe/Helsinki")).hour
    if hour < 10:
        return "morning"
    elif hour < 16:
        return "midday"
    else:
        return "evening"


async def run_swarm(cfg: dict, brief_type: str | None = None):
    """Execute a full analyst swarm run."""
    if brief_type is None:
        brief_type = _detect_brief_type()
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*60}", flush=True)
    print(f"[swarm] Starting analyst swarm run — {datetime.now().isoformat()} [{brief_type} brief]", flush=True)
    print(f"[swarm] LLM: {cfg['llm_provider']} / {cfg.get(cfg['llm_provider'], {}).get('model', '?')}", flush=True)
    print(f"{'='*60}", flush=True)

    start = time.time()
    backend_url = cfg["backend_url"]

    # Step 1: Refresh pipelines
    if cfg.get("refresh_pipelines", True):
        await report_status(backend_url, "running", message="Refreshing data pipelines...")
        await refresh_pipelines(cfg)

    # Step 2: Run analysts (parallel, excluding portfolio-manager)
    agents = cfg.get("agents", [])
    analysts = [a for a in agents if a != "portfolio-manager"]
    total_agents = len(agents)
    max_parallel = cfg.get("max_parallel", 4)

    print(f"\n[swarm] Running {len(analysts)} analysts (max {max_parallel} parallel)...", flush=True)

    semaphore = asyncio.Semaphore(max_parallel)
    completed_count = 0

    # Use per-security mode for research + technical when enabled
    per_sec_enabled = cfg.get("per_security", {}).get("enabled", False)
    per_sec_agents = {"research-analyst", "technical-analyst"}

    async def run_with_limit(agent_name):
        nonlocal completed_count
        async with semaphore:
            await report_status(backend_url, "running", agent=agent_name,
                                completed=completed_count, total=total_agents)
            if per_sec_enabled and agent_name in per_sec_agents:
                result = await run_per_security_agent(agent_name, cfg, date_str)
            else:
                result = await run_agent(agent_name, cfg, date_str)
            llm_tag = get_llm_tag()  # capture before another agent overwrites it
            completed_count += 1
            return (result, llm_tag)

    analyst_tasks = [run_with_limit(a) for a in analysts]
    results = await asyncio.gather(*analyst_tasks, return_exceptions=True)

    completed = sum(1 for r in results if r and not isinstance(r, Exception)
                     and r[0])  # r is (report, llm_tag) tuple
    failed = len(results) - completed
    print(f"\n[swarm] Analysts: {completed} completed, {failed} failed", flush=True)

    # Step 3: Extract per-security notes from research and technical analysts
    for agent_name, result in zip(analysts, results):
        if not result or isinstance(result, Exception):
            continue
        report, llm_tag = result
        if not report:
            continue
        if agent_name == "research-analyst" and not per_sec_enabled:
            # Per-security mode posts notes inline; only bulk-extract from combined reports
            await extract_per_security_notes(report, backend_url, date_str, llm_tag)
        elif agent_name == "technical-analyst":
            await extract_technical_notes(report, backend_url, date_str, llm_tag)

    # Step 4: Run portfolio manager last (needs analyst outputs + previous recommendations)
    # NOTE: old recs are closed AFTER PM runs so it can compare against them
    if "portfolio-manager" in agents:
        print("\n[swarm] Running portfolio manager (phased synthesis)...", flush=True)
        await report_status(backend_url, "running", agent="portfolio-manager",
                            completed=completed_count, total=total_agents)
        pm_report = await run_portfolio_manager_phased(cfg, date_str)
        completed_count += 1

        # Step 5: Close old recs, then post new ones from PM report
        if pm_report:
            await close_old_recommendations(backend_url)
            await report_status(backend_url, "running", message="Posting recommendations...")
            await extract_and_post_recommendations(pm_report, cfg, date_str, brief_type)

    # Step 6: Update deployment plan progress from transactions
    await update_deployment_progress(backend_url)

    # Step 7: Post-swarm health check (pipeline staleness, data gaps, etc.)
    await run_health_check(backend_url)

    elapsed = round(time.time() - start, 1)
    await report_status(backend_url, "idle",
                        completed=completed_count, total=total_agents,
                        message=f"Complete in {elapsed}s")
    print(f"\n{'='*60}", flush=True)
    print(f"[swarm] Swarm run complete in {elapsed}s", flush=True)
    print(f"{'='*60}\n", flush=True)


# ── Research-Only Run ──

async def run_research_only(cfg: dict):
    """Run just the research analyst (for nighttime watchlist rotation)."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    backend_url = cfg["backend_url"]
    print(f"\n[swarm] Research-only run — {datetime.now().isoformat()}", flush=True)

    await report_status(backend_url, "running", agent="research-analyst",
                        completed=0, total=1, message="Watchlist rotation")
    start = time.time()
    per_sec_enabled = cfg.get("per_security", {}).get("enabled", False)
    if per_sec_enabled:
        report = await run_per_security_agent("research-analyst", cfg, date_str)
    else:
        report = await run_agent("research-analyst", cfg, date_str)
    llm_tag = get_llm_tag()
    if report and not per_sec_enabled:
        # Per-security mode posts notes inline; only bulk-extract from combined reports
        await extract_per_security_notes(report, backend_url, date_str, llm_tag)
    # Health check after research run
    await run_health_check(backend_url)

    elapsed = round(time.time() - start, 1)
    await report_status(backend_url, "idle", completed=1, total=1,
                        message=f"Research complete in {elapsed}s")
    print(f"[swarm] Research-only run complete in {elapsed}s\n", flush=True)


# ── Scheduler ──

def run_swarm_sync(cfg: dict, brief_type: str | None = None):
    """Synchronous wrapper for the scheduler."""
    asyncio.run(run_swarm(cfg, brief_type))


def run_research_sync(cfg: dict):
    """Synchronous wrapper for research-only runs."""
    asyncio.run(run_research_only(cfg))


def main():
    cfg = load_config()

    # If --once flag, run immediately and exit
    if "--once" in sys.argv:
        print("[swarm] Running once (--once flag)", flush=True)
        asyncio.run(run_swarm(cfg))
        return

    # Schedule runs — map each slot to a brief type
    scheduler = BlockingScheduler(timezone="Europe/Helsinki")
    schedules = cfg.get("schedule", ["0 7 * * *", "0 12 * * *", "0 19 * * *"])
    brief_types = cfg.get("brief_types", ["morning", "midday", "evening"])

    for i, cron_expr in enumerate(schedules):
        parts = cron_expr.split()
        trigger = CronTrigger(
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4],
            timezone="Europe/Helsinki",
        )
        bt = brief_types[i] if i < len(brief_types) else None
        scheduler.add_job(run_swarm_sync, trigger, args=[cfg, bt], id=f"swarm_run_{i}")

    # Nighttime research-only runs (watchlist rotation)
    research_schedules = cfg.get("research_schedule", ["0 1 * * *", "0 3 * * *"])
    for i, cron_expr in enumerate(research_schedules):
        parts = cron_expr.split()
        trigger = CronTrigger(
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4],
            timezone="Europe/Helsinki",
        )
        scheduler.add_job(run_research_sync, trigger, args=[cfg], id=f"research_run_{i}")

    total_jobs = len(schedules) + len(research_schedules)
    print(f"[swarm] Scheduled {total_jobs} jobs:", flush=True)
    for i, s in enumerate(schedules):
        bt = brief_types[i] if i < len(brief_types) else "auto"
        print(f"  - {s} (Helsinki) [{bt} brief]", flush=True)
    for s in research_schedules:
        print(f"  - {s} (Helsinki) [research only]", flush=True)
    print(f"[swarm] LLM: {cfg['llm_provider']} / {cfg.get(cfg['llm_provider'], {}).get('model', '?')}", flush=True)
    print(f"[swarm] Watchlist rotation: {35} items per run", flush=True)
    print("[swarm] Waiting for next scheduled run...\n", flush=True)

    scheduler.start()


if __name__ == "__main__":
    main()
