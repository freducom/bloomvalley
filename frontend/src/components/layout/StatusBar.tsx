"use client";

import { useState, useEffect } from "react";
import { apiGet } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { Private } from "@/lib/privacy";

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

const EXCHANGES: Record<string, ExchangeSchedule> = {
  NYSE: {
    tz: "America/New_York",
    tradingDays: [1, 2, 3, 4, 5],
    openHour: 9,
    openMinute: 30,
    closeHour: 16,
    closeMinute: 0,
    preMarketHour: 4,
    afterHoursEndHour: 20,
  },
  NASDAQ: {
    tz: "America/New_York",
    tradingDays: [1, 2, 3, 4, 5],
    openHour: 9,
    openMinute: 30,
    closeHour: 16,
    closeMinute: 0,
    preMarketHour: 4,
    afterHoursEndHour: 20,
  },
  XHEL: {
    tz: "Europe/Helsinki",
    tradingDays: [1, 2, 3, 4, 5],
    openHour: 10,
    openMinute: 0,
    closeHour: 18,
    closeMinute: 30,
  },
};

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

export function StatusBar() {
  const [statuses, setStatuses] = useState<Record<string, MarketStatusType>>({});
  const [portfolioValue, setPortfolioValue] = useState<number | null>(null);

  useEffect(() => {
    function update() {
      const s: Record<string, MarketStatusType> = {};
      for (const [name, schedule] of Object.entries(EXCHANGES)) {
        s[name] = getExchangeStatus(schedule);
      }
      s["Crypto"] = "open"; // 24/7
      setStatuses(s);
    }
    update();
    const interval = setInterval(update, 30_000); // Update every 30s
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

  return (
    <footer className="flex items-center justify-between h-8 px-4 bg-terminal-bg-secondary border-t border-terminal-border shrink-0 text-xs font-mono">
      {/* Markets */}
      <div className="flex items-center gap-4">
        {Object.entries(statuses).map(([name, status]) => (
          <StatusDot key={name} label={name} status={status} />
        ))}
      </div>

      {/* Pipeline health */}
      <div className="flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-terminal-positive" />
        <span className="text-terminal-text-secondary">All systems operational</span>
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
}: {
  label: string;
  status: MarketStatusType;
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
    <div className="flex items-center gap-1.5">
      <div className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      <span className="text-terminal-text-secondary">
        {label}: {statusLabel}
      </span>
    </div>
  );
}
