"use client";

import { useState, useEffect } from "react";
import { apiGet, apiGetRaw } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { Private } from "@/lib/privacy";

interface PipelineStatus {
  name: string;
  isRunning: boolean;
  lastRunStatus: string | null;
}

// Cron schedule definitions (matches cron_scheduler.py, TZ=Europe/Helsinki)
interface CronJob {
  label: string;
  /** "cron" or "interval" */
  type: "cron" | "interval";
  /** For cron: { dayOfWeek?, hour, minute } */
  dayOfWeek?: string; // "mon-fri", "sun", or undefined (daily)
  hour?: number;
  minute?: number;
  /** For interval: hours between runs */
  intervalHours?: number;
}

const CRON_JOBS: CronJob[] = [
  { label: "Prices", type: "cron", dayOfWeek: "mon-fri", hour: 23, minute: 0 },
  { label: "FX Rates", type: "cron", dayOfWeek: "mon-fri", hour: 17, minute: 0 },
  { label: "Crypto", type: "interval", intervalHours: 6 },
  { label: "FRED", type: "cron", hour: 15, minute: 0 },
  { label: "ECB Macro", type: "cron", dayOfWeek: "mon-fri", hour: 12, minute: 0 },
  { label: "Dividends", type: "cron", dayOfWeek: "mon-fri", hour: 23, minute: 30 },
  { label: "News", type: "interval", intervalHours: 4 },
  { label: "Insiders (US)", type: "cron", dayOfWeek: "mon-fri", hour: 22, minute: 0 },
  { label: "Insiders (Nordic)", type: "cron", dayOfWeek: "mon-fri", hour: 19, minute: 0 },
  { label: "Insiders (FI/SE)", type: "cron", dayOfWeek: "mon-fri", hour: 19, minute: 30 },
  { label: "Alpha Vantage", type: "cron", dayOfWeek: "mon-fri", hour: 0, minute: 0 },
  { label: "justETF", type: "cron", dayOfWeek: "sun", hour: 10, minute: 0 },
  { label: "SEC Edgar", type: "cron", dayOfWeek: "mon-fri", hour: 21, minute: 0 },
  { label: "Congress", type: "cron", dayOfWeek: "mon-fri", hour: 20, minute: 0 },
  { label: "Morningstar", type: "cron", dayOfWeek: "sun", hour: 11, minute: 0 },
  { label: "Factors", type: "cron", dayOfWeek: "sun", hour: 12, minute: 0 },
  { label: "GDELT", type: "interval", intervalHours: 6 },
  { label: "Regional News", type: "interval", intervalHours: 4 },
  { label: "Fundamentals", type: "cron", dayOfWeek: "mon-fri", hour: 23, minute: 45 },
  { label: "News Cleanup", type: "cron", hour: 4, minute: 0 },
  { label: "Research Cleanup", type: "cron", hour: 4, minute: 30 },
  // Analyst swarm (from analyst-swarm/config.yaml)
  { label: "Analyst Swarm", type: "cron", hour: 7, minute: 0 },
  { label: "Analyst Swarm", type: "cron", hour: 12, minute: 0 },
  { label: "Analyst Swarm", type: "cron", hour: 19, minute: 0 },
  { label: "Research Swarm", type: "cron", hour: 1, minute: 0 },
  { label: "Research Swarm", type: "cron", hour: 3, minute: 0 },
];

const DOW_MAP: Record<string, number[]> = {
  "mon-fri": [1, 2, 3, 4, 5],
  sun: [0],
};

function getNextCronRun(): { label: string; timeStr: string; relativeStr: string } | null {
  const tz = "Europe/Helsinki";
  const now = new Date();

  // Get current Helsinki time components
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
    weekday: "short",
  });
  const parts = fmt.formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value || "";
  const dayNameMap: Record<string, number> = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 0 };
  const curDay = dayNameMap[get("weekday")] ?? 0;
  const curHour = parseInt(get("hour"), 10);
  const curMin = parseInt(get("minute"), 10);
  const curTotalMin = curHour * 60 + curMin;

  let bestLabel = "";
  let bestMinutesAway = Infinity;

  for (const job of CRON_JOBS) {
    if (job.type === "interval") {
      // Interval jobs: approximate — next run within intervalHours
      // We can't know exactly when they started, so show worst case
      const mins = (job.intervalHours || 4) * 60;
      if (mins < bestMinutesAway) {
        bestMinutesAway = mins;
        bestLabel = job.label;
      }
      continue;
    }

    const allowedDays = job.dayOfWeek ? (DOW_MAP[job.dayOfWeek] || [0,1,2,3,4,5,6]) : [0,1,2,3,4,5,6];
    const jobMin = (job.hour || 0) * 60 + (job.minute || 0);

    // Check today and next 7 days
    for (let d = 0; d <= 7; d++) {
      const checkDay = (curDay + d) % 7;
      if (!allowedDays.includes(checkDay)) continue;

      let minutesAway: number;
      if (d === 0) {
        if (jobMin <= curTotalMin) continue; // already passed today
        minutesAway = jobMin - curTotalMin;
      } else {
        minutesAway = (d * 24 * 60) - curTotalMin + jobMin;
      }

      if (minutesAway < bestMinutesAway) {
        bestMinutesAway = minutesAway;
        bestLabel = job.label;
      }
      break; // found earliest occurrence for this job
    }
  }

  if (!bestLabel) return null;

  // Format time string
  const nextDate = new Date(now.getTime() + bestMinutesAway * 60_000);
  const timeFmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const timeStr = timeFmt.format(nextDate);

  // Relative string
  const h = Math.floor(bestMinutesAway / 60);
  const m = bestMinutesAway % 60;
  let relativeStr: string;
  if (h > 0 && m > 0) relativeStr = `in ${h}h ${m}m`;
  else if (h > 0) relativeStr = `in ${h}h`;
  else relativeStr = `in ${m}m`;

  return { label: bestLabel, timeStr, relativeStr };
}

const PIPELINE_LABELS: Record<string, string> = {
  yahoo_daily_prices: "Prices",
  ecb_fx_rates: "FX Rates",
  coingecko_prices: "Crypto",
  fred_macro_indicators: "FRED",
  ecb_macro_indicators: "ECB Macro",
  yahoo_dividends: "Dividends",
  google_news: "News",
  regional_news: "Regional News",
  openinsider: "Insiders (US)",
  nasdaq_nordic_insider: "Insiders (Nordic)",
  fi_se_insider: "Insiders (FI/SE)",
  yahoo_fundamentals: "Fundamentals",
  alpha_vantage_prices: "Alpha Vantage",
  sec_edgar_filings: "SEC Edgar",
  quiver_congress_trades: "Congress",
  morningstar_ratings: "Morningstar",
  french_factors: "Factors",
  gdelt_events: "GDELT",
  justetf_profiles: "justETF",
  finnhub_earnings: "Earnings",
  news_cleanup: "Cleanup",
};

type MarketStatusType = "open" | "closed" | "pre-market" | "after-hours";

interface MarketStatusEntry {
  label: string;
  status: MarketStatusType;
  tooltip?: string;
}

export function StatusBar() {
  const [statuses, setStatuses] = useState<Record<string, { status: MarketStatusType; tooltip?: string }>>({});
  const [portfolioValue, setPortfolioValue] = useState<number | null>(null);

  // Fetch market status from backend (holiday/half-day aware via exchange_calendars)
  useEffect(() => {
    function fetchMarkets() {
      apiGetRaw<{ data: MarketStatusEntry[] }>("/markets/status")
        .then((res) => {
          const s: Record<string, { status: MarketStatusType; tooltip?: string }> = {};
          for (const entry of res.data) {
            s[entry.label] = { status: entry.status, tooltip: entry.tooltip };
          }
          setStatuses(s);
        })
        .catch(() => {});
    }
    fetchMarkets();
    const interval = setInterval(fetchMarkets, 30_000);
    return () => clearInterval(interval);
  }, []);

  const [runningPipelines, setRunningPipelines] = useState<string[]>([]);
  const [failedCount, setFailedCount] = useState(0);
  const [nextCron, setNextCron] = useState<{ label: string; timeStr: string; relativeStr: string } | null>(null);

  useEffect(() => {
    setNextCron(getNextCronRun());
    const interval = setInterval(() => setNextCron(getNextCronRun()), 30_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    apiGet<{ totalValueEurCents: number }>("/portfolio/summary")
      .then((d) => setPortfolioValue(d.totalValueEurCents))
      .catch(() => {});
    const interval = setInterval(() => {
      apiGet<{ totalValueEurCents: number }>("/portfolio/summary")
        .then((d) => setPortfolioValue(d.totalValueEurCents))
        .catch(() => {});
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  const [swarmStatus, setSwarmStatus] = useState<{
    status: string;
    agent?: string;
    completed?: number;
    total?: number;
    message?: string;
  } | null>(null);

  // Poll pipeline + swarm status
  useEffect(() => {
    function fetchStatus() {
      apiGetRaw<{ data: PipelineStatus[] }>("/pipelines")
        .then((res) => {
          const running = res.data
            .filter((p) => p.isRunning)
            .map((p) => PIPELINE_LABELS[p.name] || p.name);
          const failed = res.data.filter((p) => p.lastRunStatus === "failed").length;
          setRunningPipelines(running);
          setFailedCount(failed);
        })
        .catch(() => {});
      apiGetRaw<{ data: { status: string; agent?: string; completed?: number; total?: number; message?: string } }>("/swarm/status")
        .then((res) => setSwarmStatus(res.data))
        .catch(() => {});
    }
    fetchStatus();
    const interval = setInterval(fetchStatus, 10_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <footer className="flex items-center justify-between h-8 px-4 bg-terminal-bg-secondary border-t border-terminal-border shrink-0 text-xs font-mono">
      {/* Markets — hidden on mobile */}
      <div className="hidden md:flex items-center gap-4">
        {Object.entries(statuses).map(([name, info]) => (
          <StatusDot key={name} label={name} status={info.status} tooltip={info.tooltip} />
        ))}
      </div>

      {/* System status */}
      <div className="flex items-center gap-4 min-w-0">
        {/* Swarm status */}
        {swarmStatus?.status === "running" && (
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
            <span className="text-purple-400 truncate">
              {swarmStatus.agent
                ? `${swarmStatus.agent} (${swarmStatus.completed || 0}/${swarmStatus.total || 0})`
                : swarmStatus.message || "Swarm running"}
            </span>
          </div>
        )}
        {/* Pipeline status */}
        {runningPipelines.length > 0 ? (
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-terminal-accent animate-pulse" />
            <span className="text-terminal-accent truncate">
              {runningPipelines.join(", ")}
            </span>
          </div>
        ) : failedCount > 0 ? (
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-terminal-warning" />
            <span className="text-terminal-text-secondary">
              {failedCount} failed
            </span>
          </div>
        ) : swarmStatus?.status !== "running" ? (
          <div
            className="flex items-center gap-1.5 cursor-default"
            title={nextCron ? `Next: ${nextCron.label} at ${nextCron.timeStr} (${nextCron.relativeStr})` : undefined}
          >
            <div className="w-1.5 h-1.5 rounded-full bg-terminal-positive" />
            <span className="text-terminal-text-secondary hidden md:inline">All systems functional</span>
          </div>
        ) : null}
      </div>

      {/* Portfolio value */}
      <div className="flex items-center gap-2">
        <span className="text-terminal-text-secondary hidden md:inline">Portfolio:</span>
        <span className="font-semibold text-terminal-text-primary">
          <Private>{portfolioValue !== null ? formatCurrency(portfolioValue) : "—"}</Private>
        </span>
      </div>
    </footer>
  );
}

function StatusDot({
  label,
  status,
  tooltip,
}: {
  label: string;
  status: MarketStatusType;
  tooltip?: string;
}) {
  const dotColor = {
    open: "bg-terminal-positive",
    closed: "bg-terminal-text-tertiary",
    "pre-market": "bg-terminal-warning",
    "after-hours": "bg-terminal-warning",
  }[status];

  const statusLabel = {
    open: "Open",
    closed: "Closed",
    "pre-market": "Pre",
    "after-hours": "After",
  }[status];

  return (
    <div className="flex items-center gap-1.5 cursor-default" title={tooltip}>
      <div className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      <span className="text-terminal-text-secondary">
        {label}: {statusLabel}
      </span>
    </div>
  );
}
