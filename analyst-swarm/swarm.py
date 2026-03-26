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
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# API key for backend authentication
_API_KEY = os.environ.get("API_KEY", "")
_AUTH_HEADERS = {"X-API-Key": _API_KEY} if _API_KEY else {}

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

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": cfg["ollama"]["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {
                    "num_predict": cfg["ollama"].get("max_tokens", 8192),
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


async def call_claude_cli(prompt: str, system: str, cfg: dict) -> str:
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
            timeout=600,
        )

        if proc.returncode != 0:
            err = stderr.decode().strip()
            raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {err[:500]}")

        return stdout.decode().strip()
    finally:
        os.unlink(tmp_path)


async def call_llm(prompt: str, system: str, cfg: dict) -> str:
    """Route to the configured LLM backend."""
    provider = cfg.get("llm_provider", "claude")
    if provider == "claude":
        return await call_claude(prompt, system, cfg)
    elif provider == "claude_cli":
        return await call_claude_cli(prompt, system, cfg)
    elif provider == "ollama":
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
                            batch_size = 20
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
        "/portfolio/holdings", "/portfolio/summary", "/risk/metrics",
        "/risk/stress-tests", "/risk/glidepath", "/macro/regime",
    ],
    "quant-analyst": [
        "/portfolio/holdings", "/portfolio/summary", "/risk/metrics",
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
    ],
    "technical-analyst": [
        "/portfolio/holdings", "/screener/munger",
        "/charts/heatmap?source=holdings&period=1W",
    ],
    "compliance-officer": [
        "/portfolio/holdings", "/portfolio/summary", "/insiders/signals",
        "/news?limit=10", "/alerts?status=active", "/transactions?limit=50",
        "/risk/glidepath", "/macro/regime", "/pipelines",
    ],
    "portfolio-manager": [
        "/portfolio/holdings", "/portfolio/summary", "/transactions?limit=50",
        "/dividends/upcoming", "/risk/metrics", "/risk/stress-tests",
        "/watchlists/", "/screener/munger", "/insiders/signals",
        "/news?limit=20", "/macro/summary", "/macro/regime",
        "/fundamentals?limit=200", "/recommendations?status=active&limit=50",
        "/research/notes?tag=research-analyst&limit=100",
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


def build_prompt(agent_name: str, agent_def: str, data: dict[str, str], date_str: str) -> tuple[str, str]:
    """Build system prompt and user prompt for an agent."""
    system = f"""You are the {agent_name} for the Bloomvalley investment terminal.
Follow your agent definition exactly. Today's date is {date_str}.
The backend API data has been pre-fetched and provided below.
Produce your complete analysis report. Be specific with numbers, dates, and actionable recommendations."""

    data_section = "\n\n".join(
        f"### Data from {ep}\n```json\n{content[:15000]}\n```"
        for ep, content in data.items()
        if not content.startswith("ERROR")
    )

    user_prompt = f"""# Agent Definition

{agent_def}

# Pre-fetched API Data

{data_section}

# Instructions

Analyze the data above and produce your complete report following the format in your agent definition.
Today is {date_str}. Be concrete and specific."""

    return system, user_prompt


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
                "tags": ["analyst_report", agent_name, "swarm"],
            })
        except Exception as e:
            print(f"  [!] Failed to store report for {agent_name}: {e}", flush=True)


# ── Research Analyst: Per-Security Extraction ──

# Matches "## 1. TICKER — Name" and "## W-1. TICKER — Name"
_SECTION_RE = re.compile(
    r"^## (?:W-)?(\d+)\. ([A-Z][A-Z0-9._-]+) — (.+?)$",
    re.MULTILINE,
)


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


async def extract_per_security_notes(report: str, backend_url: str, date_str: str):
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
                         "watchlist" if sec["is_watchlist"] else "held"],
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

        # For technical analyst, also fetch OHLC for top holdings
        if agent_name == "technical-analyst":
            # Get security IDs from holdings
            try:
                holdings_raw = data.get("/portfolio/holdings", "[]")
                holdings = json.loads(holdings_raw) if not holdings_raw.startswith("ERROR") else []
                if isinstance(holdings, dict):
                    holdings = holdings.get("data", [])
                for h in holdings[:10]:
                    sid = h.get("securityId")
                    if sid:
                        extra = await fetch_data(backend_url, [f"/charts/{sid}/ohlc?period=6M&indicators=sma,ema,rsi,macd,bb"])
                        data.update(extra)
            except Exception:
                pass

        # Build prompt
        system, user_prompt = build_prompt(agent_name, agent_def, data, date_str)

        # Call LLM
        report = await call_llm(user_prompt, system, cfg)

        # Store report
        await store_report(backend_url, agent_name, report)

        elapsed = round(time.time() - start, 1)
        print(f"  [{agent_name}] Complete ({elapsed}s, {len(report)} chars)", flush=True)
        return report

    except Exception as e:
        elapsed = round(time.time() - start, 1)
        print(f"  [{agent_name}] FAILED after {elapsed}s: {e}", flush=True)
        return None


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


EXTRACT_RECS_PROMPT = """Extract ALL actionable recommendations from this portfolio manager report.
Return a JSON array of objects. Each object must have these fields:
- "ticker": string (e.g. "VWCE", "ALYK", "MSFT", "INVE-B.ST", "KESKOB.HE")
- "action": "buy" | "sell" | "hold"
- "confidence": "high" | "medium" | "low"
- "rationale": string (1-3 sentence summary of the recommendation)
- "bull_case": string or null
- "bear_case": string or null
- "time_horizon": "short" | "medium" | "long" (short=<3m, medium=3-12m, long=>12m)

Include ALL recommendations from the report, including hold recommendations.
For "sell" actions on funds being redeemed, use "sell".
Return ONLY the JSON array, no markdown fences, no explanation."""


async def extract_and_post_recommendations(report: str, cfg: dict, date_str: str):
    """Parse the PM report into structured recommendations and POST them."""
    backend_url = cfg["backend_url"]
    print("  [pm] Extracting recommendations from report...", flush=True)

    try:
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

    except Exception as e:
        print(f"  [pm] Failed to extract recommendations: {e}", flush=True)


# ── Main Swarm Run ──

async def run_swarm(cfg: dict):
    """Execute a full analyst swarm run."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*60}", flush=True)
    print(f"[swarm] Starting analyst swarm run — {datetime.now().isoformat()}", flush=True)
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

    async def run_with_limit(agent_name):
        nonlocal completed_count
        async with semaphore:
            await report_status(backend_url, "running", agent=agent_name,
                                completed=completed_count, total=total_agents)
            result = await run_agent(agent_name, cfg, date_str)
            completed_count += 1
            return result

    analyst_tasks = [run_with_limit(a) for a in analysts]
    results = await asyncio.gather(*analyst_tasks, return_exceptions=True)

    completed = sum(1 for r in results if r and not isinstance(r, Exception))
    failed = len(results) - completed
    print(f"\n[swarm] Analysts: {completed} completed, {failed} failed", flush=True)

    # Step 3: Extract per-security research notes
    for agent_name, result in zip(analysts, results):
        if agent_name == "research-analyst" and result and not isinstance(result, Exception):
            await extract_per_security_notes(result, backend_url, date_str)
            break

    # Step 4: Close old recommendations
    if "portfolio-manager" in agents:
        await close_old_recommendations(backend_url)

    # Step 5: Run portfolio manager last (needs analyst outputs)
    if "portfolio-manager" in agents:
        print("\n[swarm] Running portfolio manager (final synthesis)...", flush=True)
        await report_status(backend_url, "running", agent="portfolio-manager",
                            completed=completed_count, total=total_agents)
        pm_report = await run_agent("portfolio-manager", cfg, date_str)
        completed_count += 1

        # Step 6: Extract and post structured recommendations from PM report
        if pm_report:
            await report_status(backend_url, "running", message="Posting recommendations...")
            await extract_and_post_recommendations(pm_report, cfg, date_str)

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
    report = await run_agent("research-analyst", cfg, date_str)
    if report:
        await extract_per_security_notes(report, backend_url, date_str)
    elapsed = round(time.time() - start, 1)
    await report_status(backend_url, "idle", completed=1, total=1,
                        message=f"Research complete in {elapsed}s")
    print(f"[swarm] Research-only run complete in {elapsed}s\n", flush=True)


# ── Scheduler ──

def run_swarm_sync(cfg: dict):
    """Synchronous wrapper for the scheduler."""
    asyncio.run(run_swarm(cfg))


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

    # Schedule runs
    scheduler = BlockingScheduler(timezone="Europe/Helsinki")
    schedules = cfg.get("schedule", ["0 7 * * *", "0 12 * * *", "0 19 * * *"])

    for i, cron_expr in enumerate(schedules):
        parts = cron_expr.split()
        trigger = CronTrigger(
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4],
            timezone="Europe/Helsinki",
        )
        scheduler.add_job(run_swarm_sync, trigger, args=[cfg], id=f"swarm_run_{i}")

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
    for s in schedules:
        print(f"  - {s} (Helsinki) [full swarm]", flush=True)
    for s in research_schedules:
        print(f"  - {s} (Helsinki) [research only]", flush=True)
    print(f"[swarm] LLM: {cfg['llm_provider']} / {cfg.get(cfg['llm_provider'], {}).get('model', '?')}", flush=True)
    print(f"[swarm] Watchlist rotation: {20} items per run", flush=True)
    print("[swarm] Waiting for next scheduled run...\n", flush=True)

    scheduler.start()


if __name__ == "__main__":
    main()
