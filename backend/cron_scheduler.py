"""
Pipeline scheduler using APScheduler.
Runs inside Docker, triggers pipelines via HTTP calls to the backend.
"""

import os

import httpx
from apscheduler.schedulers.blocking import BlockingScheduler


BACKEND_URL = "http://backend:8000/api/v1/pipelines"
BACKEND_BASE_URL = "http://backend:8000/api/v1"
_API_KEY = os.environ.get("API_KEY", "")
_HEADERS = {"X-API-Key": _API_KEY} if _API_KEY else {}


def trigger(name: str) -> None:
    try:
        r = httpx.post(f"{BACKEND_URL}/{name}/run", timeout=300, headers=_HEADERS)
        print(f"[cron] {name} -> {r.status_code}", flush=True)
    except Exception as e:
        print(f"[cron] {name} FAILED: {e}", flush=True)


def trigger_endpoint(path: str, label: str) -> None:
    """Trigger an arbitrary backend endpoint (non-pipeline)."""
    try:
        r = httpx.post(f"{BACKEND_BASE_URL}/{path}", timeout=300, headers=_HEADERS)
        print(f"[cron] {label} -> {r.status_code}", flush=True)
    except Exception as e:
        print(f"[cron] {label} FAILED: {e}", flush=True)


def main() -> None:
    scheduler = BlockingScheduler(timezone="Europe/Helsinki")

    # Yahoo Finance prices — weekdays at 23:00 Helsinki time (after markets close)
    scheduler.add_job(trigger, "cron", args=["yahoo_daily_prices"],
                      day_of_week="mon-fri", hour=23, minute=0,
                      id="yahoo_daily_prices")

    # ECB FX rates — weekdays at 17:00 Helsinki time (ECB publishes ~16:00 CET)
    scheduler.add_job(trigger, "cron", args=["ecb_fx_rates"],
                      day_of_week="mon-fri", hour=17, minute=0,
                      id="ecb_fx_rates")

    # CoinGecko crypto prices — every 6 hours
    scheduler.add_job(trigger, "interval", args=["coingecko_prices"],
                      hours=6, id="coingecko_prices")

    # FRED macro indicators — daily at 15:00 Helsinki time
    scheduler.add_job(trigger, "cron", args=["fred_macro_indicators"],
                      hour=15, minute=0, id="fred_macro_indicators")

    # ECB macro indicators — weekdays at 12:00 Helsinki time
    scheduler.add_job(trigger, "cron", args=["ecb_macro_indicators"],
                      day_of_week="mon-fri", hour=12, minute=0,
                      id="ecb_macro_indicators")

    # Yahoo dividends — weekdays at 23:30 Helsinki time
    scheduler.add_job(trigger, "cron", args=["yahoo_dividends"],
                      day_of_week="mon-fri", hour=23, minute=30,
                      id="yahoo_dividends")

    # Google News — every 4 hours
    scheduler.add_job(trigger, "interval", args=["google_news"],
                      hours=4, id="google_news")

    # OpenInsider — weekdays at 22:00 Helsinki time
    scheduler.add_job(trigger, "cron", args=["openinsider"],
                      day_of_week="mon-fri", hour=22, minute=0,
                      id="openinsider")

    # Nasdaq Nordic insider trades — weekdays at 19:00 Helsinki time
    scheduler.add_job(trigger, "cron", args=["nasdaq_nordic_insider"],
                      day_of_week="mon-fri", hour=19, minute=0,
                      id="nasdaq_nordic_insider")

    # FI/SE insider trades — weekdays at 19:30 Helsinki time
    scheduler.add_job(trigger, "cron", args=["fi_se_insider"],
                      day_of_week="mon-fri", hour=19, minute=30,
                      id="fi_se_insider")

    # Alpha Vantage backup prices — weekdays at 00:00 (fills gaps from Yahoo)
    scheduler.add_job(trigger, "cron", args=["alpha_vantage_prices"],
                      day_of_week="mon-fri", hour=0, minute=0,
                      id="alpha_vantage_prices")

    # justETF profiles — weekly on Sunday at 10:00
    scheduler.add_job(trigger, "cron", args=["justetf_profiles"],
                      day_of_week="sun", hour=10, minute=0,
                      id="justetf_profiles")

    # SEC EDGAR filings — weekdays at 21:00 Helsinki time
    scheduler.add_job(trigger, "cron", args=["sec_edgar_filings"],
                      day_of_week="mon-fri", hour=21, minute=0,
                      id="sec_edgar_filings")

    # Quiver Congress trades — weekdays at 20:00 Helsinki time
    scheduler.add_job(trigger, "cron", args=["quiver_congress_trades"],
                      day_of_week="mon-fri", hour=20, minute=0,
                      id="quiver_congress_trades")

    # Morningstar ratings — weekly on Sunday at 11:00
    scheduler.add_job(trigger, "cron", args=["morningstar_ratings"],
                      day_of_week="sun", hour=11, minute=0,
                      id="morningstar_ratings")

    # Kenneth French factor data — weekly on Sunday at 12:00
    scheduler.add_job(trigger, "cron", args=["french_factors"],
                      day_of_week="sun", hour=12, minute=0,
                      id="french_factors")

    # GDELT global events — every 6 hours
    scheduler.add_job(trigger, "interval", args=["gdelt_events"],
                      hours=6, id="gdelt_events")

    # Regional news (Reuters, ECB, Kauppalehti, DI, Nikkei) — every 4 hours
    scheduler.add_job(trigger, "interval", args=["regional_news"],
                      hours=4, id="regional_news")

    # Yahoo fundamentals (ROIC, P/B, FCF, margins, DCF) — weekdays at 23:45
    scheduler.add_job(trigger, "cron", args=["yahoo_fundamentals"],
                      day_of_week="mon-fri", hour=23, minute=45,
                      id="yahoo_fundamentals")

    # News retention cleanup — daily at 04:00 Helsinki time
    scheduler.add_job(trigger_endpoint, "cron",
                      args=["news/cleanup", "news_cleanup"],
                      hour=4, minute=0, id="news_cleanup")

    # Research notes retention cleanup — daily at 04:30 Helsinki time
    scheduler.add_job(trigger_endpoint, "cron",
                      args=["research/cleanup", "research_cleanup"],
                      hour=4, minute=30, id="research_cleanup")

    jobs = scheduler.get_jobs()
    print(f"[cron] Starting scheduler with {len(jobs)} jobs (TZ=Europe/Helsinki):", flush=True)
    for job in jobs:
        print(f"  - {job.id}: {job.trigger}", flush=True)

    scheduler.start()


if __name__ == "__main__":
    main()
