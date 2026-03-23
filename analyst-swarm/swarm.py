"""
Analyst Swarm Orchestrator — runs all investment analyst agents on a schedule.
Supports Claude API and Ollama as LLM backends.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

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


async def call_llm(prompt: str, system: str, cfg: dict) -> str:
    """Route to the configured LLM backend."""
    provider = cfg.get("llm_provider", "claude")
    if provider == "claude":
        return await call_claude(prompt, system, cfg)
    elif provider == "ollama":
        return await call_ollama(prompt, system, cfg)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


# ── Data Fetching ──

async def fetch_data(backend_url: str, endpoints: list[str]) -> dict[str, str]:
    """Fetch data from multiple API endpoints."""
    results = {}
    async with httpx.AsyncClient(timeout=60, base_url=backend_url) as client:
        for ep in endpoints:
            try:
                resp = await client.get(ep)
                if resp.status_code == 200:
                    results[ep] = resp.text
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

    async with httpx.AsyncClient(timeout=30, base_url=backend_url) as client:
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
            async with httpx.AsyncClient(timeout=10, base_url=backend_url) as client:
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
    async with httpx.AsyncClient(timeout=30, base_url=backend_url) as client:
        try:
            await client.post("/research/notes", json={
                "title": f"{agent_name.replace('-', ' ').title()} — {datetime.now().strftime('%Y-%m-%d')}",
                "thesis": report[:10000],
                "tags": ["analyst_report", agent_name, "swarm"],
            })
        except Exception as e:
            print(f"  [!] Failed to store report for {agent_name}: {e}", flush=True)


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
    async with httpx.AsyncClient(timeout=30, base_url=backend_url) as client:
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


# ── Main Swarm Run ──

async def run_swarm(cfg: dict):
    """Execute a full analyst swarm run."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*60}", flush=True)
    print(f"[swarm] Starting analyst swarm run — {datetime.now().isoformat()}", flush=True)
    print(f"[swarm] LLM: {cfg['llm_provider']} / {cfg.get(cfg['llm_provider'], {}).get('model', '?')}", flush=True)
    print(f"{'='*60}", flush=True)

    start = time.time()

    # Step 1: Refresh pipelines
    if cfg.get("refresh_pipelines", True):
        await refresh_pipelines(cfg)

    # Step 2: Run analysts (parallel, excluding portfolio-manager)
    agents = cfg.get("agents", [])
    analysts = [a for a in agents if a != "portfolio-manager"]
    max_parallel = cfg.get("max_parallel", 4)

    print(f"\n[swarm] Running {len(analysts)} analysts (max {max_parallel} parallel)...", flush=True)

    semaphore = asyncio.Semaphore(max_parallel)

    async def run_with_limit(agent_name):
        async with semaphore:
            return await run_agent(agent_name, cfg, date_str)

    analyst_tasks = [run_with_limit(a) for a in analysts]
    results = await asyncio.gather(*analyst_tasks, return_exceptions=True)

    completed = sum(1 for r in results if r and not isinstance(r, Exception))
    failed = len(results) - completed
    print(f"\n[swarm] Analysts: {completed} completed, {failed} failed", flush=True)

    # Step 3: Close old recommendations
    if "portfolio-manager" in agents:
        await close_old_recommendations(cfg["backend_url"])

    # Step 4: Run portfolio manager last (needs analyst outputs)
    if "portfolio-manager" in agents:
        print("\n[swarm] Running portfolio manager (final synthesis)...", flush=True)
        await run_agent("portfolio-manager", cfg, date_str)

    elapsed = round(time.time() - start, 1)
    print(f"\n{'='*60}", flush=True)
    print(f"[swarm] Swarm run complete in {elapsed}s", flush=True)
    print(f"{'='*60}\n", flush=True)


# ── Scheduler ──

def run_swarm_sync(cfg: dict):
    """Synchronous wrapper for the scheduler."""
    asyncio.run(run_swarm(cfg))


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

    print(f"[swarm] Scheduled {len(schedules)} runs:", flush=True)
    for s in schedules:
        print(f"  - {s} (Helsinki)", flush=True)
    print(f"[swarm] LLM: {cfg['llm_provider']} / {cfg.get(cfg['llm_provider'], {}).get('model', '?')}", flush=True)
    print("[swarm] Waiting for next scheduled run...\n", flush=True)

    scheduler.start()


if __name__ == "__main__":
    main()
