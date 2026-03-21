"""
Investment Team Agent Orchestrator

Runs the 9-agent investment team in a staged pipeline:
  Wave 1 (parallel): Research Analyst, Quant Analyst, Technical Analyst,
                      Macro Strategist, Fixed Income Analyst, Tax Strategist
  Wave 2: Risk Manager (needs portfolio context)
  Wave 3: Portfolio Manager (synthesizes all inputs, generates recommendations)
  Wave 4: Compliance Officer (validates recommendations)

Each agent is a Claude subagent that reads data from the API,
performs analysis, and writes results back via API endpoints.

Usage:
    python scripts/run_agents.py [--wave N] [--agent NAME] [--dry-run]
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = PROJECT_ROOT / ".claude" / "agents"
API_BASE = "http://localhost:8000/api/v1"


# ── Agent Definitions ────────────────────────────────────────────────

WAVE_1_AGENTS = [
    {
        "name": "research-analyst",
        "file": "research-analyst.md",
        "task": f"""You are the Research Analyst for the Warren Cashett investment terminal.

Your job RIGHT NOW: Analyze all securities on the watchlists and portfolio holdings.
For each security, produce a research note with bull/bear cases.

STEP 1: Fetch the data you need:
- GET {API_BASE}/watchlists/ to get all watchlists
- GET {API_BASE}/watchlists/{{id}} for each watchlist to get security IDs
- GET {API_BASE}/portfolio/holdings to get current holdings
- GET {API_BASE}/securities/{{id}} for each security's details
- GET {API_BASE}/prices/latest for current prices
- GET {API_BASE}/dividends/calendar for dividend data
- GET {API_BASE}/insiders/signals for insider activity

STEP 2: For each security, write a research note via:
- POST {API_BASE}/research/notes with body (camelCase!):
  {{"securityId": <id>, "title": "<ticker> Research Note",
    "thesis": "<investment thesis>",
    "bullCase": "<best realistic scenario with target price>",
    "bearCase": "<worst realistic scenario with downside>",
    "baseCase": "<most likely outcome>",
    "intrinsicValueCents": <int or null>, "intrinsicValueCurrency": "EUR",
    "marginOfSafetyPct": <float or null>,
    "moatRating": "none|narrow|wide",
    "tags": ["auto-generated"]}}

STEP 3: Write fundamentals data via:
- POST {API_BASE}/fundamentals with body:
  {{"security_id": <id>, "price_to_book": <float>, "free_cash_flow_cents": <int>,
    "dcf_value_cents": <int>, "dcf_discount_rate": <float>, "dcf_terminal_growth": <float>,
    "dcf_notes": "<method used>", "institutional_ownership_pct": <float>,
    "smart_money_signal": "accumulating|distributing|neutral"}}

Focus on the HOLDINGS first, then the watchlist securities with highest weight.
Use the sector-appropriate valuation method (DCF for industrials, P/B for banks, etc.).
Work through as many securities as you can. Be thorough but efficient.""",
    },
    {
        "name": "quant-analyst",
        "file": "quant-analyst.md",
        "task": f"""You are the Quantitative Analyst for the Warren Cashett investment terminal.

Your job RIGHT NOW: Screen all watchlist securities, compute factor scores, and update fundamentals.

STEP 1: Fetch data:
- GET {API_BASE}/watchlists/ to get all watchlists and their items
- GET {API_BASE}/securities to get all tracked securities
- GET {API_BASE}/prices/latest for current prices
- GET {API_BASE}/charts/{{security_id}}/ohlc?period=1y for price history (sample top 20 by weight)

STEP 2: For each security compute and POST fundamentals:
- POST {API_BASE}/fundamentals with factor scores:
  {{"security_id": <id>, "price_to_book": <float>,
    "short_interest_pct": <float if known>, "short_interest_change_pct": <float>,
    "short_squeeze_risk": "low|medium|high",
    "smart_money_signal": "accumulating|distributing|neutral",
    "smart_money_outlook": "<90-day outlook>"}}

STEP 3: Post earnings analysis for securities with available data:
- POST {API_BASE}/fundamentals/earnings with:
  {{"security_id": <id>, "fiscal_year": 2025, "quarter": 4,
    "revenue_cents": <int>, "revenue_yoy_pct": <float>,
    "eps_cents": <int>, "eps_yoy_pct": <float>,
    "gross_margin_pct": <float>, "operating_margin_pct": <float>,
    "forward_guidance": "<text>", "red_flags": "<any concerns>",
    "recommendation": "buy|hold|sell", "recommendation_reasoning": "<why>"}}

Focus on computing quantitative metrics. Use price history to estimate momentum and volatility.""",
    },
    {
        "name": "technical-analyst",
        "file": "technical-analyst.md",
        "task": f"""You are the Technical Analyst for the Warren Cashett investment terminal.

Your job RIGHT NOW: Provide technical signals for all holdings and key watchlist stocks.

STEP 1: Fetch data:
- GET {API_BASE}/portfolio/holdings for current positions
- GET {API_BASE}/watchlists/ for watchlist securities
- GET {API_BASE}/prices/latest for current prices
- For key securities: GET {API_BASE}/charts/{{security_id}}/ohlc?period=1y

STEP 2: For each analyzed security, save a research note:
- POST {API_BASE}/research/notes with (camelCase!):
  {{"securityId": <id>, "title": "<ticker> Technical Analysis",
    "thesis": "<trend assessment, MA signals, RSI, support/resistance, entry/exit levels>",
    "tags": ["technical", "auto-generated"]}}

Focus on holdings first, then personal watchlist stocks.
Key signals: 50/200 MA crossovers, RSI overbought/oversold, support/resistance levels.""",
    },
    {
        "name": "macro-strategist",
        "file": "macro-strategist.md",
        "task": f"""You are the Macro Strategist / Sector Rotation Analyst for the Warren Cashett investment terminal.

You have called every major sector rotation of the last 20 years before it became obvious. Now do it again.

STEP 1: Fetch data:
- GET {API_BASE}/macro/summary for latest macro indicators
- GET {API_BASE}/macro/yield-curve?region=eu for Euro yield curve
- GET {API_BASE}/macro/yield-curve?region=us for US yield curve
- GET {API_BASE}/news/sentiment-summary for news sentiment
- GET {API_BASE}/news?limit=50 for recent news
- GET {API_BASE}/portfolio/holdings for current holdings (check sector exposure)
- GET {API_BASE}/portfolio/summary for portfolio overview
- GET {API_BASE}/watchlists/ for watchlist universe

STEP 2: Save your SECTOR ROTATION CALL as a research note:
- POST {API_BASE}/research/notes with (camelCase!):
  {{"title": "Sector Rotation Call - March 2026",
    "thesis": "<full analysis — see required sections below>",
    "tags": ["macro", "sector-rotation", "auto-generated"]}}

Your note MUST include ALL of the following sections:
1. REGIME ASSESSMENT: Where are we in the cycle? (Early/Mid/Late/Recession/Recovery). How many months until transition?
2. SECTORS TO OVERWEIGHT (next 12 months): Why now, historical analog, catalyst timeline, specific securities from our watchlists
3. SECTORS TO AVOID COMPLETELY: Why, what would change your mind, flag any current holdings in these sectors
4. THE ONE INDICATOR: The single most important number to watch right now. Current reading, trigger threshold, what to do when it triggers, lead time
5. RISKS TO THIS VIEW: What would invalidate your entire thesis
6. ASSET CLASS TILTS: Over/underweight equities, bonds, cash, crypto
7. RATE OUTLOOK: ECB + Fed trajectory and impact on sector positioning

Be specific. Name securities from the portfolio and watchlists. Give numbers and timeframes, not vague hedging.""",
    },
    {
        "name": "fixed-income-analyst",
        "file": "fixed-income-analyst.md",
        "task": f"""You are the Fixed Income Analyst for the Warren Cashett investment terminal.

Your job RIGHT NOW: Assess fixed income allocation and recommend bond positioning.

STEP 1: Fetch data:
- GET {API_BASE}/fixed-income/summary for current FI allocation
- GET {API_BASE}/fixed-income/portfolio for bond holdings
- GET {API_BASE}/fixed-income/glidepath for glidepath status
- GET {API_BASE}/fixed-income/income-projection for income needs
- GET {API_BASE}/macro/yield-curve for yield curves
- GET {API_BASE}/macro/summary for rate data

STEP 2: Save analysis as research note:
- POST {API_BASE}/research/notes with (camelCase!):
  {{"title": "Fixed Income Review - March 2026",
    "thesis": "<FI allocation vs target, duration recommendation, yield analysis, bond ladder>",
    "tags": ["fixed-income", "auto-generated"]}}

Key: The investor is 45, targeting 60% fixed income by age 60. Currently should be ~15% FI.
Assess: Are we on track? What bonds should we add? Duration positioning given rate outlook.""",
    },
    {
        "name": "tax-strategist",
        "file": "tax-strategist.md",
        "task": f"""You are the Tax Strategist for the Warren Cashett investment terminal.

Your job RIGHT NOW: Analyze tax position and identify optimization opportunities.

STEP 1: Fetch data:
- GET {API_BASE}/portfolio/summary for overview
- GET {API_BASE}/portfolio/holdings for all positions
- GET {API_BASE}/prices/latest for current prices

STEP 2: Save tax analysis:
- POST {API_BASE}/research/notes with (camelCase!):
  {{"title": "Tax Strategy Review - March 2026",
    "thesis": "<YTD gains, loss harvesting candidates, OST strategy, account structure>",
    "tags": ["tax", "auto-generated"]}}

Finnish tax rules: 30% capital gains up to €30k, 34% above. OST (osakesäästötili) has ~€50k cap.
Assess: OST utilization, loss harvesting opportunities, which account to use for new purchases.""",
    },
]

WAVE_2_AGENTS = [
    {
        "name": "risk-manager",
        "file": "risk-manager.md",
        "task": f"""You are the Risk Manager for the Warren Cashett investment terminal.

Your job RIGHT NOW: Assess portfolio risk and flag any policy violations.

STEP 1: Fetch data:
- GET {API_BASE}/risk for risk metrics
- GET {API_BASE}/portfolio/summary for portfolio overview
- GET {API_BASE}/portfolio/holdings for position details
- GET {API_BASE}/prices/latest for current prices
- GET {API_BASE}/macro/summary for macro context

STEP 2: Save risk assessment:
- POST {API_BASE}/research/notes with (camelCase!):
  {{"title": "Risk Assessment - March 2026",
    "thesis": "<risk dashboard, concentration alerts, stress tests, glidepath status>",
    "tags": ["risk", "auto-generated"]}}

STEP 3: Create alerts for any violations:
- POST {API_BASE}/alerts with:
  {{"security_id": <id or null>, "alert_type": "risk_breach",
    "condition_type": "above|below", "threshold_value": <float>,
    "message": "<what's breached>"}}

Check: position limits (<5% single stock, <20% sector), crypto allocation (5-10%),
glidepath compliance, concentration risk, correlation clusters.""",
    },
]

WAVE_3_AGENTS = [
    {
        "name": "portfolio-manager",
        "file": "portfolio-manager.md",
        "task": f"""You are the Portfolio Manager (Lead) for the Warren Cashett investment terminal.

Your job RIGHT NOW: Review all analyst inputs and generate actionable recommendations.

STEP 1: Read all analyst inputs:
- GET {API_BASE}/research/notes?limit=50 for all research notes
- GET {API_BASE}/fundamentals for fundamentals data
- GET {API_BASE}/fundamentals/earnings for earnings data
- GET {API_BASE}/portfolio/summary for current portfolio
- GET {API_BASE}/portfolio/holdings for positions
- GET {API_BASE}/risk for risk status
- GET {API_BASE}/fixed-income/glidepath for glidepath status
- GET {API_BASE}/insiders/signals for insider signals
- GET {API_BASE}/prices/latest for current prices
- GET {API_BASE}/watchlists/ for watchlist universe

STEP 2: Generate recommendations with mandatory bull AND bear cases:
- POST {API_BASE}/recommendations with:
  {{"security_id": <id>, "action": "buy|sell|hold",
    "target_price_cents": <int>, "stop_loss_cents": <int>,
    "confidence": "high|medium|low", "reasoning": "<rationale>",
    "bull_case": "<best realistic scenario with numbers>",
    "bear_case": "<worst realistic scenario with numbers>",
    "tags": ["auto-generated"]}}

RULES:
- Bull and bear cases are MANDATORY for every recommendation, no exceptions
- Consider the glidepath (age 45, target 60% FI by 60)
- No single stock >5%, no sector >20%
- Prefer ACC ETFs for tax efficiency
- Long-term focus, minimum holding period mindset
- Synthesize research, quant, technical, macro, risk, tax, and FI inputs

Generate recommendations for: rebalancing needs, new buy candidates from watchlists,
any sells needed for risk/concentration/glidepath compliance.""",
    },
]

WAVE_4_AGENTS = [
    {
        "name": "compliance-officer",
        "file": "compliance-officer.md",
        "task": f"""You are the Compliance Officer for the Warren Cashett investment terminal.

Your job RIGHT NOW: Validate all new recommendations against investment policy.

STEP 1: Fetch data:
- GET {API_BASE}/recommendations?status=active for all active recommendations
- GET {API_BASE}/portfolio/summary for portfolio overview
- GET {API_BASE}/portfolio/holdings for current positions
- GET {API_BASE}/risk for risk metrics

STEP 2: For each recommendation, check:
- Position would not exceed 5% of portfolio
- Sector would not exceed 20%
- Crypto stays within 5-10% range
- Cash stays above 3%
- No leverage, options, or margin
- ACC ETFs preferred over distributing
- Glidepath compliance (age 45: ~75% equity, ~15% FI, ~7% crypto, ~3% cash)
- Bull AND bear cases are present

STEP 3: Save compliance review:
- POST {API_BASE}/research/notes with (camelCase!):
  {{"title": "Compliance Review - March 2026",
    "thesis": "<PASS/FAIL for each recommendation, violations, conditions>",
    "tags": ["compliance", "auto-generated"]}}

Flag any recommendations that violate policy. Be strict — protect the portfolio.""",
    },
]

WAVES = [
    ("Wave 1: Parallel Analysts", WAVE_1_AGENTS),
    ("Wave 2: Risk Manager", WAVE_2_AGENTS),
    ("Wave 3: Portfolio Manager", WAVE_3_AGENTS),
    ("Wave 4: Compliance Officer", WAVE_4_AGENTS),
]


# ── Agent Runner ─────────────────────────────────────────────────────

def run_agent(agent: dict, dry_run: bool = False) -> dict:
    """Run a single Claude agent via the claude CLI."""
    name = agent["name"]
    agent_file = AGENTS_DIR / agent["file"]
    task = agent["task"]

    print(f"  [{name}] Starting...", flush=True)
    start = time.time()

    if dry_run:
        time.sleep(1)
        elapsed = time.time() - start
        print(f"  [{name}] DRY RUN complete ({elapsed:.1f}s)", flush=True)
        return {"name": name, "status": "dry_run", "elapsed": elapsed}

    try:
        # Remove CLAUDECODE env var to allow nested sessions
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--agent", str(agent_file),
                "--max-turns", "30",
                "--model", "sonnet",
                "-p", task,
            ],
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min per agent
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        elapsed = time.time() - start
        status = "success" if result.returncode == 0 else "failed"

        if result.returncode != 0:
            print(f"  [{name}] FAILED ({elapsed:.1f}s): {result.stderr[:200]}", flush=True)
        else:
            # Count meaningful output lines
            output_lines = len(result.stdout.strip().split("\n"))
            print(f"  [{name}] Complete ({elapsed:.1f}s, {output_lines} lines output)", flush=True)

        return {
            "name": name,
            "status": status,
            "elapsed": elapsed,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"  [{name}] TIMEOUT ({elapsed:.1f}s)", flush=True)
        return {"name": name, "status": "timeout", "elapsed": elapsed}
    except FileNotFoundError:
        print(f"  [{name}] ERROR: 'claude' CLI not found in PATH", flush=True)
        return {"name": name, "status": "error", "elapsed": 0}


def run_wave(wave_name: str, agents: list, dry_run: bool = False, max_parallel: int = 6):
    """Run a wave of agents, potentially in parallel."""
    print(f"\n{'='*60}", flush=True)
    print(f"  {wave_name} ({len(agents)} agents)", flush=True)
    print(f"{'='*60}", flush=True)

    results = []

    if len(agents) == 1:
        # Single agent — run directly
        results.append(run_agent(agents[0], dry_run))
    else:
        # Multiple agents — run in parallel
        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            futures = {
                executor.submit(run_agent, agent, dry_run): agent
                for agent in agents
            }
            for future in as_completed(futures):
                results.append(future.result())

    return results


def main():
    parser = argparse.ArgumentParser(description="Run the investment team agents")
    parser.add_argument("--wave", type=int, help="Run only this wave (1-4)")
    parser.add_argument("--agent", type=str, help="Run only this agent by name")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually run agents")
    parser.add_argument("--max-parallel", type=int, default=6, help="Max parallel agents")
    args = parser.parse_args()

    print("=" * 60)
    print("  Warren Cashett — Investment Team Orchestrator")
    print("=" * 60)

    # Single agent mode
    if args.agent:
        all_agents = [a for wave in WAVES for a in wave[1]]
        agent = next((a for a in all_agents if a["name"] == args.agent), None)
        if not agent:
            print(f"Unknown agent: {args.agent}")
            print(f"Available: {', '.join(a['name'] for a in all_agents)}")
            sys.exit(1)
        results = [run_agent(agent, args.dry_run)]
    else:
        # Wave mode
        results = []
        waves_to_run = WAVES if not args.wave else [WAVES[args.wave - 1]]

        for wave_name, agents in waves_to_run:
            wave_results = run_wave(wave_name, agents, args.dry_run, args.max_parallel)
            results.extend(wave_results)

            # Check for failures before proceeding to next wave
            failures = [r for r in wave_results if r["status"] not in ("success", "dry_run")]
            if failures:
                failed_names = ", ".join(r["name"] for r in failures)
                print(f"\n  WARNING: {len(failures)} agent(s) failed in {wave_name}: {failed_names}")
                print(f"  Continuing to next wave anyway...")

    # Summary
    print(f"\n{'='*60}")
    print(f"  Summary")
    print(f"{'='*60}")
    total_time = sum(r.get("elapsed", 0) for r in results)
    for r in results:
        status_icon = {"success": "+", "dry_run": "~", "failed": "!", "timeout": "!!", "error": "X"}
        icon = status_icon.get(r["status"], "?")
        print(f"  [{icon}] {r['name']:25s} {r['status']:10s} ({r.get('elapsed', 0):.1f}s)")
    print(f"\n  Total wall time: {total_time:.1f}s")
    print(f"  Agents: {len(results)} total, {sum(1 for r in results if r['status'] == 'success')} succeeded")


if __name__ == "__main__":
    main()
