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

interface ExchangeSchedule {
  /** Timezone string for Intl.DateTimeFormat */
  tz: string;
  /** Trading days: 1=Mon..5=Fri */
  tradingDays: number[];
  /** Open hour (local) */
  openHour: number;
  openMinute: number;
  /** Close hour (local) */
  closeHour: number;
  closeMinute: number;
  /** Pre-market opens (optional) */
  preMarketHour?: number;
  /** After-hours ends (optional) */
  afterHoursEndHour?: number;
}

// Market groups — exchanges that share the same trading hours shown as one entry.
// Each group has a display label, schedule, and the MIC codes it covers.
const MARKET_GROUPS: { label: string; mics: string[]; schedule: ExchangeSchedule }[] = [
  {
    label: "Nordic",
    mics: ["XHEL", "XSTO", "XCSE"],
    schedule: {
      tz: "Europe/Helsinki",
      tradingDays: [1, 2, 3, 4, 5],
      openHour: 10, openMinute: 0,  // 10:00 EET = 09:00 CET
      closeHour: 18, closeMinute: 30,
    },
  },
  {
    label: "EU",
    mics: ["XAMS", "XETR", "XPAR", "XSWX"],
    schedule: {
      tz: "Europe/Paris",
      tradingDays: [1, 2, 3, 4, 5],
      openHour: 9, openMinute: 0,
      closeHour: 17, closeMinute: 30,
    },
  },
  {
    label: "London",
    mics: ["XLON"],
    schedule: {
      tz: "Europe/London",
      tradingDays: [1, 2, 3, 4, 5],
      openHour: 8, openMinute: 0,
      closeHour: 16, closeMinute: 30,
    },
  },
  {
    label: "US",
    mics: ["XNYS", "XNAS", "NMS", "NGS", "NYQ"],
    schedule: {
      tz: "America/New_York",
      tradingDays: [1, 2, 3, 4, 5],
      openHour: 9, openMinute: 30,
      closeHour: 16, closeMinute: 0,
      preMarketHour: 4,
      afterHoursEndHour: 20,
    },
  },
];

function getLocalTime(tz: string): { hour: number; minute: number; dayOfWeek: number } {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "numeric",
    weekday: "short",
    hour12: false,
  }).formatToParts(now);

  let hour = 0;
  let minute = 0;
  let weekday = "";
  for (const p of parts) {
    if (p.type === "hour") hour = parseInt(p.value, 10);
    if (p.type === "minute") minute = parseInt(p.value, 10);
    if (p.type === "weekday") weekday = p.value;
  }

  // Handle midnight edge case: Intl may return 24 as 0
  const dayMap: Record<string, number> = {
    Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 0,
  };
  return { hour, minute, dayOfWeek: dayMap[weekday] ?? 0 };
}

function _fmtDuration(totalMin: number): string {
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  return `${m}m`;
}

function _getLocalParts(tz: string): { day: number; minutes: number } {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "2-digit", minute: "2-digit", hour12: false,
    weekday: "short",
  }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value || "";
  const dayMap: Record<string, number> = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 0 };
  return {
    day: dayMap[get("weekday")] ?? 0,
    minutes: parseInt(get("hour"), 10) * 60 + parseInt(get("minute"), 10),
  };
}

function getTimeUntilOpen(schedule: ExchangeSchedule): string {
  const { day, minutes } = _getLocalParts(schedule.tz);
  const openMin = schedule.openHour * 60 + schedule.openMinute;

  // Opens later today?
  if (schedule.tradingDays.includes(day) && minutes < openMin) {
    return `Opens in ${_fmtDuration(openMin - minutes)}`;
  }

  // Find next trading day
  let daysAhead = 1;
  for (let i = 1; i <= 7; i++) {
    if (schedule.tradingDays.includes((day + i) % 7)) { daysAhead = i; break; }
  }

  if (daysAhead === 1) {
    return `Opens in ${_fmtDuration(24 * 60 - minutes + openMin)}`;
  }

  const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const openStr = `${String(schedule.openHour).padStart(2, "0")}:${String(schedule.openMinute).padStart(2, "0")}`;
  return `Opens ${dayNames[(day + daysAhead) % 7]} ${openStr}`;
}

function getTimeUntilClose(schedule: ExchangeSchedule): string {
  const { minutes } = _getLocalParts(schedule.tz);
  const closeMin = schedule.closeHour * 60 + schedule.closeMinute;
  if (minutes < closeMin) {
    return `Closes in ${_fmtDuration(closeMin - minutes)}`;
  }
  return "Closing soon";
}

function getExchangeStatus(schedule: ExchangeSchedule): MarketStatusType {
  const { hour, minute, dayOfWeek } = getLocalTime(schedule.tz);
  const timeMinutes = hour * 60 + minute;

  if (!schedule.tradingDays.includes(dayOfWeek)) return "closed";

  const openMinutes = schedule.openHour * 60 + schedule.openMinute;
  const closeMinutes = schedule.closeHour * 60 + schedule.closeMinute;

  if (timeMinutes >= openMinutes && timeMinutes < closeMinutes) return "open";

  if (schedule.preMarketHour !== undefined) {
    const preMinutes = schedule.preMarketHour * 60;
    if (timeMinutes >= preMinutes && timeMinutes < openMinutes) return "pre-market";
  }

  if (schedule.afterHoursEndHour !== undefined) {
    const afterMinutes = schedule.afterHoursEndHour * 60;
    if (timeMinutes >= closeMinutes && timeMinutes < afterMinutes) return "after-hours";
  }

  return "closed";
}

interface SecurityInfo {
  exchange: string | null;
  assetClass: string;
}

export function StatusBar() {
  const [statuses, setStatuses] = useState<Record<string, { status: MarketStatusType; tooltip?: string }>>({});
  const [portfolioValue, setPortfolioValue] = useState<number | null>(null);
  const [activeGroups, setActiveGroups] = useState<typeof MARKET_GROUPS>([]);
  const [hasCrypto, setHasCrypto] = useState(false);

  // Fetch exchanges from all tracked securities, match to market groups
  useEffect(() => {
    apiGet<SecurityInfo[]>("/securities")
      .then((secs) => {
        const exchanges = new Set<string>();
        let crypto = false;
        for (const s of secs) {
          if (s.exchange) exchanges.add(s.exchange);
          if (s.assetClass === "crypto") crypto = true;
        }
        setHasCrypto(crypto);
        const groups = MARKET_GROUPS.filter((g) =>
          g.mics.some((mic) => exchanges.has(mic))
        );
        setActiveGroups(groups);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    function update() {
      const s: Record<string, { status: MarketStatusType; tooltip?: string }> = {};
      for (const group of activeGroups) {
        const status = getExchangeStatus(group.schedule);
        const tooltip = status === "open"
          ? getTimeUntilClose(group.schedule)
          : getTimeUntilOpen(group.schedule);
        s[group.label] = { status, tooltip };
      }
      if (hasCrypto) {
        s["Crypto"] = { status: "open", tooltip: "24/7 market" };
      }
      setStatuses(s);
    }
    update();
    const interval = setInterval(update, 30_000);
    return () => clearInterval(interval);
  }, [activeGroups, hasCrypto]);

  const [runningPipelines, setRunningPipelines] = useState<string[]>([]);
  const [failedCount, setFailedCount] = useState(0);

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
    <footer className="hidden md:flex items-center justify-between h-8 px-4 bg-terminal-bg-secondary border-t border-terminal-border shrink-0 text-xs font-mono">
      {/* Markets */}
      <div className="flex items-center gap-4">
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
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-terminal-positive" />
            <span className="text-terminal-text-secondary">OK</span>
          </div>
        ) : null}
      </div>

      {/* Portfolio value */}
      <div className="flex items-center gap-2">
        <span className="text-terminal-text-secondary">Portfolio:</span>
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
