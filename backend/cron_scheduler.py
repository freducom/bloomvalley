"""
Pipeline scheduler using APScheduler.
Runs inside Docker, triggers pipelines via HTTP calls to the backend.
"""

import httpx
from apscheduler.schedulers.blocking import BlockingScheduler


BACKEND_URL = "http://backend:8000/api/v1/pipelines"


def trigger(name: str) -> None:
    try:
        r = httpx.post(f"{BACKEND_URL}/{name}/run", timeout=300)
        print(f"[cron] {name} -> {r.status_code}", flush=True)
    except Exception as e:
        print(f"[cron] {name} FAILED: {e}", flush=True)


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

    jobs = scheduler.get_jobs()
    print(f"[cron] Starting scheduler with {len(jobs)} jobs (TZ=Europe/Helsinki):", flush=True)
    for job in jobs:
        print(f"  - {job.id}: {job.trigger}", flush=True)

    scheduler.start()


if __name__ == "__main__":
    main()
