#!/usr/bin/env python3
"""One-shot: run deep Claude research analysis on ALL watchlist + held securities.

Bypasses the 35-item rotation limit and forces claude_cli provider.
Usage: docker compose exec analyst-swarm python run_full_claude.py
"""
import asyncio
import json
import sys
import os

# Force claude_cli provider
os.environ.pop("OLLAMA_BASE_URL", None)
os.environ.pop("OLLAMA_MODEL", None)

from swarm import (
    load_config, fetch_data, run_per_security_agent,
    extract_per_security_notes, get_llm_tag,
    _AUTH_HEADERS, report_status,
)
from datetime import datetime
import httpx


async def fetch_all_watchlist_items(backend_url: str) -> list[dict]:
    """Fetch ALL watchlist items (no rotation/batching)."""
    async with httpx.AsyncClient(timeout=60, base_url=backend_url, headers=_AUTH_HEADERS) as client:
        resp = await client.get("/watchlists/")
        if resp.status_code != 200:
            return []
        wl_data = resp.json().get("data", [])
        all_items = []
        seen = set()
        for wl in wl_data:
            if wl.get("itemCount", 0) > 0:
                wl_resp = await client.get(f"/watchlists/{wl['id']}")
                if wl_resp.status_code == 200:
                    for item in wl_resp.json().get("data", {}).get("items", []):
                        ticker = item.get("ticker")
                        if ticker and ticker not in seen:
                            item["watchlistName"] = wl["name"]
                            all_items.append(item)
                            seen.add(ticker)
        return all_items


async def main():
    cfg = load_config()

    # Force claude_cli — remove ollama fallback to ensure we use Claude
    cfg["llm_provider"] = "claude_cli"
    # Increase concurrency for Claude (faster than Ollama)
    cfg.setdefault("per_security", {})["max_concurrent"] = 3
    cfg["per_security"]["timeout_per_call"] = 300

    backend_url = cfg["backend_url"]
    date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"[full-claude] Deep analysis run — {datetime.now().isoformat()}")
    print(f"{'='*60}\n")

    # Get ALL watchlist items (bypass rotation)
    print("[full-claude] Fetching all watchlist items...", flush=True)
    all_items = await fetch_all_watchlist_items(backend_url)
    print(f"[full-claude] Found {len(all_items)} unique watchlist items", flush=True)

    # Monkey-patch fetch_data to inject all items instead of rotated batch
    original_fetch = fetch_data.__wrapped__ if hasattr(fetch_data, '__wrapped__') else None

    import swarm as swarm_module
    _original_fetch_data = swarm_module.fetch_data

    async def patched_fetch_data(backend_url, endpoints):
        results = await _original_fetch_data(backend_url, endpoints)
        # Override watchlist items with ALL items (no rotation)
        if "/watchlists/" in endpoints:
            results["/watchlists/items"] = json.dumps({"data": all_items})
        return results

    swarm_module.fetch_data = patched_fetch_data

    try:
        await report_status(backend_url, "running", agent="research-analyst",
                            message="Full Claude deep analysis (all securities)")

        report = await run_per_security_agent("research-analyst", cfg, date_str)
        llm_tag = get_llm_tag()

        if report:
            await extract_per_security_notes(report, backend_url, date_str, llm_tag)
            print(f"\n[full-claude] Analysis complete! LLM: {llm_tag}", flush=True)
        else:
            print("[full-claude] No report generated", flush=True)

        await report_status(backend_url, "idle",
                            message="Full Claude deep analysis complete")
    finally:
        swarm_module.fetch_data = _original_fetch_data

    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
