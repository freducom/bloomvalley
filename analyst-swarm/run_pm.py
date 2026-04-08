#!/usr/bin/env python3
"""One-shot: run portfolio manager using Claude CLI.

Uses the latest research notes (including fresh Claude deep analysis).
Usage: docker compose exec analyst-swarm python run_pm.py
"""
import asyncio
from datetime import datetime

from swarm import (
    load_config, run_agent, report_status, get_llm_tag,
    close_old_recommendations, extract_and_post_recommendations,
)


async def main():
    cfg = load_config()
    cfg["llm_provider"] = "claude_cli"

    backend_url = cfg["backend_url"]
    date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"[pm-run] Portfolio Manager — {datetime.now().isoformat()}")
    print(f"{'='*60}\n")

    await report_status(backend_url, "running", agent="portfolio-manager",
                        message="Portfolio Manager (Claude, using deep research)")

    pm_report = await run_agent("portfolio-manager", cfg, date_str)

    if pm_report:
        llm_tag = get_llm_tag()
        print(f"\n[pm-run] Report generated ({len(pm_report)} chars, {llm_tag})", flush=True)
        print("[pm-run] Closing old recommendations and posting new ones...", flush=True)
        await close_old_recommendations(backend_url)
        await extract_and_post_recommendations(pm_report, cfg, date_str, "manual")
        print("[pm-run] Done!", flush=True)
    else:
        print("[pm-run] No report generated", flush=True)

    await report_status(backend_url, "idle",
                        message="Portfolio Manager complete")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
