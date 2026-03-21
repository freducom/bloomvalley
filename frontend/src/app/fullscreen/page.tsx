"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  X,
  Maximize,
  Minimize,
  EyeOff,
  Eye,
  TrendingUp,
  TrendingDown,
  Coins,
  BarChart3,
  Bell,
  Clock,
  Newspaper,
} from "lucide-react";
import { apiGet } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { usePrivacy, Private } from "@/lib/privacy";

// --- Types ---

interface PortfolioSummary {
  totalValueEurCents: number;
  totalCostEurCents: number;
  unrealizedPnlCents: number;
  unrealizedPnlPct: number;
  holdingsCount: number;
  allocation: Record<string, number>;
}

interface Holding {
  securityId: number;
  ticker: string;
  name: string;
  assetClass: string;
  quantity: string;
  currentPriceCents: number;
  priceCurrency: string;
  marketValueCents: number;
  marketValueEurCents: number;
  unrealizedPnlCents: number;
  unrealizedPnlPct: number;
}

interface Recommendation {
  id: number;
  ticker: string;
  securityName: string;
  action: string;
  confidence: string;
  rationale: string;
  recommendedDate: string;
}

interface NewsItem {
  id: number;
  title: string;
  source: string;
  publishedAt: string;
  securities: { ticker: string }[];
}

interface AlertItem {
  id: number;
  type: string;
  status: string;
  ticker: string | null;
  securityName: string | null;
  message: string;
  createdAt: string;
}

// --- Helpers ---

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return "now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

function allocationPercent(allocation: Record<string, number>): { label: string; pct: number; color: string }[] {
  const total = Object.values(allocation).reduce((a, b) => a + b, 0);
  if (total === 0) return [];
  const colors: Record<string, string> = {
    stock: "#3B82F6",
    etf: "#8B5CF6",
    crypto: "#F59E0B",
    fixed_income: "#22C55E",
    cash: "#6B7280",
    other: "#9CA3AF",
  };
  const labels: Record<string, string> = {
    stock: "Equities",
    etf: "ETFs",
    crypto: "Crypto",
    fixed_income: "Fixed Income",
    cash: "Cash",
  };
  return Object.entries(allocation)
    .filter(([, v]) => v > 0)
    .map(([k, v]) => ({
      label: labels[k] || k,
      pct: (v / total) * 100,
      color: colors[k] || "#9CA3AF",
    }))
    .sort((a, b) => b.pct - a.pct);
}

// --- Component ---

export default function FullscreenDashboard() {
  const router = useRouter();
  const { privacyMode, togglePrivacy } = usePrivacy();
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [time, setTime] = useState(new Date());
  const containerRef = useRef<HTMLDivElement>(null);

  // Data state
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Clock
  useEffect(() => {
    const i = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(i);
  }, []);

  // Market status
  const getMarketStatus = useCallback(() => {
    const hel = new Intl.DateTimeFormat("en-US", {
      timeZone: "Europe/Helsinki",
      hour: "numeric",
      minute: "numeric",
      weekday: "short",
      hour12: false,
    }).formatToParts(time);

    let hour = 0, minute = 0, weekday = "";
    for (const p of hel) {
      if (p.type === "hour") hour = parseInt(p.value);
      if (p.type === "minute") minute = parseInt(p.value);
      if (p.type === "weekday") weekday = p.value;
    }
    const m = hour * 60 + minute;
    const isWeekday = ["Mon", "Tue", "Wed", "Thu", "Fri"].includes(weekday);

    if (!isWeekday) return { label: "Market Closed", color: "text-terminal-negative", dot: "bg-terminal-negative" };
    if (m >= 540 && m < 600) return { label: "Pre-Market", color: "text-terminal-warning", dot: "bg-terminal-warning" };
    if (m >= 600 && m < 1110) return { label: "Market Open", color: "text-terminal-positive", dot: "bg-terminal-positive" };
    return { label: "Market Closed", color: "text-terminal-negative", dot: "bg-terminal-negative" };
  }, [time]);

  const marketStatus = getMarketStatus();

  // Fetch data
  const fetchAll = useCallback(async () => {
    try {
      const [s, h, r, n, a] = await Promise.allSettled([
        apiGet<PortfolioSummary>("/portfolio/summary"),
        apiGet<Holding[]>("/portfolio/holdings"),
        apiGet<Recommendation[]>("/recommendations?limit=5&sort=-recommended_date"),
        apiGet<NewsItem[]>("/news?limit=10"),
        apiGet<AlertItem[]>("/alerts?status=active&limit=5"),
      ]);
      if (s.status === "fulfilled") setSummary(s.value);
      if (h.status === "fulfilled") setHoldings(h.value);
      if (r.status === "fulfilled") setRecommendations(r.value);
      if (n.status === "fulfilled") setNews(n.value);
      if (a.status === "fulfilled") setAlerts(a.value);
      setLastUpdated(new Date());
    } catch {}
  }, []);

  useEffect(() => {
    fetchAll();
    const i = setInterval(fetchAll, 60_000);
    return () => clearInterval(i);
  }, [fetchAll]);

  // Fullscreen toggle
  const toggleFullscreen = useCallback(async () => {
    try {
      if (!document.fullscreenElement) {
        await containerRef.current?.requestFullscreen();
        setIsFullscreen(true);
      } else {
        await document.exitFullscreen();
        setIsFullscreen(false);
      }
    } catch {}
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "f") {
        e.preventDefault();
        toggleFullscreen();
      }
      if (e.key === "Escape" && !document.fullscreenElement) {
        router.push("/portfolio");
      }
    };
    document.addEventListener("keydown", handler);

    const fsChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", fsChange);

    return () => {
      document.removeEventListener("keydown", handler);
      document.removeEventListener("fullscreenchange", fsChange);
    };
  }, [toggleFullscreen, router]);

  // Top movers - sorted by absolute unrealized PnL %
  const topMovers = [...holdings]
    .filter((h) => h.unrealizedPnlPct !== null && h.unrealizedPnlPct !== undefined)
    .sort((a, b) => Math.abs(b.unrealizedPnlPct) - Math.abs(a.unrealizedPnlPct))
    .slice(0, 10);

  const maxAbsPct = Math.max(...topMovers.map((h) => Math.abs(h.unrealizedPnlPct)), 1);

  // Allocation data
  const alloc = summary ? allocationPercent(summary.allocation) : [];

  const helsinkiTime = time.toLocaleTimeString("fi-FI", {
    timeZone: "Europe/Helsinki",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-[200] bg-terminal-bg-primary flex flex-col overflow-hidden"
    >
      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-terminal-border shrink-0">
        <div className="flex items-center gap-4">
          <span className="font-mono font-bold text-xl text-terminal-accent">Bloomvalley</span>
          <span className="text-terminal-text-tertiary text-sm">Terminal</span>
        </div>

        <div className="flex items-center gap-3">
          {/* Market status */}
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${marketStatus.dot} ${marketStatus.dot.includes("positive") ? "animate-pulse" : ""}`} />
            <span className={`font-mono text-sm ${marketStatus.color}`}>{marketStatus.label}</span>
          </div>

          {/* Clock */}
          <span className="font-mono text-lg text-terminal-text-secondary ml-2">{helsinkiTime}</span>

          {/* Privacy toggle */}
          <button
            onClick={togglePrivacy}
            className={`p-1.5 rounded transition-colors ${privacyMode ? "text-terminal-warning hover:bg-terminal-bg-tertiary" : "text-terminal-text-tertiary hover:bg-terminal-bg-tertiary hover:text-terminal-text-primary"}`}
            title={`Privacy ${privacyMode ? "On" : "Off"} (Cmd+Shift+P)`}
          >
            {privacyMode ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>

          {/* Fullscreen toggle */}
          <button
            onClick={toggleFullscreen}
            className="p-1.5 rounded text-terminal-text-tertiary hover:bg-terminal-bg-tertiary hover:text-terminal-text-primary transition-colors"
            title="Toggle fullscreen (Cmd+Shift+F)"
          >
            {isFullscreen ? <Minimize size={18} /> : <Maximize size={18} />}
          </button>

          {/* Exit */}
          <button
            onClick={() => router.push("/portfolio")}
            className="p-1.5 rounded text-terminal-text-tertiary hover:bg-terminal-bg-tertiary hover:text-terminal-negative transition-colors"
            title="Exit (Esc)"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Grid */}
      <div className="flex-1 grid grid-cols-[2fr_1fr] grid-rows-3 gap-[2px] p-[2px] min-h-0">
        {/* Panel 1: Portfolio Summary */}
        <div className="bg-terminal-bg-secondary rounded p-6 flex flex-col justify-center overflow-hidden">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-terminal-text-tertiary text-sm mb-1 uppercase tracking-wider">Portfolio Value</div>
              <div className="font-mono text-5xl font-bold text-terminal-text-primary mb-2">
                <Private>{summary ? formatCurrency(summary.totalValueEurCents) : "---"}</Private>
              </div>
              {summary && (
                <div className={`font-mono text-2xl ${summary.unrealizedPnlCents >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                  <Private>
                    {summary.unrealizedPnlCents >= 0 ? "+" : ""}
                    {formatCurrency(summary.unrealizedPnlCents)}
                  </Private>
                  {" "}
                  <span className="text-lg">
                    ({summary.unrealizedPnlPct >= 0 ? "+" : ""}{summary.unrealizedPnlPct.toFixed(2)}%)
                  </span>
                </div>
              )}
              <div className="text-terminal-text-tertiary text-xs mt-2">
                {summary?.holdingsCount ?? 0} holdings across {summary ? Object.keys(summary.allocation).length : 0} asset classes
              </div>
            </div>

            {/* Allocation bar */}
            <div className="w-64 shrink-0 ml-8">
              <div className="text-terminal-text-tertiary text-xs uppercase tracking-wider mb-2">Allocation</div>
              <div className="w-full h-4 rounded-sm overflow-hidden flex">
                {alloc.map((a) => (
                  <div
                    key={a.label}
                    style={{ width: `${a.pct}%`, backgroundColor: a.color }}
                    title={`${a.label}: ${a.pct.toFixed(1)}%`}
                  />
                ))}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
                {alloc.map((a) => (
                  <div key={a.label} className="flex items-center gap-1.5">
                    <div className="w-2 h-2 rounded-sm" style={{ backgroundColor: a.color }} />
                    <span className="text-xs text-terminal-text-secondary">{a.label}</span>
                    <span className="text-xs font-mono text-terminal-text-primary">{a.pct.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Panel 2: Market Pulse / Alerts */}
        <div className="bg-terminal-bg-secondary rounded p-5 overflow-hidden flex flex-col">
          <div className="text-terminal-text-tertiary text-xs uppercase tracking-wider mb-3 flex items-center gap-2">
            <Bell size={14} />
            Active Alerts
          </div>
          <div className="flex-1 overflow-y-auto space-y-2">
            {alerts.length === 0 && (
              <div className="text-terminal-text-tertiary text-sm">No active alerts</div>
            )}
            {alerts.map((a) => (
              <div key={a.id} className="flex items-start gap-2 py-1.5 border-b border-terminal-border last:border-0">
                <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                  a.type === "risk_breach" ? "bg-terminal-negative" :
                  a.type === "price_target" ? "bg-terminal-positive" :
                  "bg-terminal-warning"
                }`} />
                <div className="min-w-0">
                  {a.ticker && (
                    <span className="text-xs font-mono text-terminal-accent mr-1.5">{a.ticker}</span>
                  )}
                  <span className="text-xs text-terminal-text-secondary leading-relaxed line-clamp-2">
                    {a.message.length > 120 ? a.message.slice(0, 120) + "..." : a.message}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Panel 3: Top Movers */}
        <div className="bg-terminal-bg-secondary rounded p-5 overflow-hidden flex flex-col">
          <div className="text-terminal-text-tertiary text-xs uppercase tracking-wider mb-3 flex items-center gap-2">
            <TrendingUp size={14} />
            Holdings Performance
          </div>
          <div className="flex-1 overflow-y-auto space-y-1">
            {topMovers.map((h) => {
              const pct = h.unrealizedPnlPct;
              const isPositive = pct >= 0;
              const barWidth = (Math.abs(pct) / maxAbsPct) * 100;

              return (
                <div key={h.securityId} className="flex items-center gap-3 h-8">
                  <span className="font-mono text-xs text-terminal-text-primary w-20 shrink-0 truncate">{h.ticker}</span>
                  <span className="text-xs text-terminal-text-secondary w-44 shrink-0 truncate">{h.name}</span>
                  <div className="flex-1 flex items-center h-5">
                    {isPositive ? (
                      <div className="flex-1 flex justify-start">
                        <div
                          className="h-4 rounded-sm bg-terminal-positive/40"
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                    ) : (
                      <div className="flex-1 flex justify-end">
                        <div
                          className="h-4 rounded-sm bg-terminal-negative/40"
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                    )}
                  </div>
                  <span className={`font-mono text-xs w-16 text-right shrink-0 ${isPositive ? "text-terminal-positive" : "text-terminal-negative"}`}>
                    {isPositive ? "+" : ""}{pct.toFixed(1)}%
                  </span>
                  <span className="font-mono text-xs w-20 text-right shrink-0 text-terminal-text-secondary">
                    <Private>{formatCurrency(h.marketValueEurCents)}</Private>
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Panel 4: Recommendations */}
        <div className="bg-terminal-bg-secondary rounded p-5 overflow-hidden flex flex-col">
          <div className="text-terminal-text-tertiary text-xs uppercase tracking-wider mb-3 flex items-center gap-2">
            <BarChart3 size={14} />
            Latest Recommendations
          </div>
          <div className="flex-1 overflow-y-auto space-y-2">
            {recommendations.length === 0 && (
              <div className="text-terminal-text-tertiary text-sm">No recommendations yet</div>
            )}
            {recommendations.map((r) => {
              const actionColor = {
                buy: "bg-terminal-positive text-terminal-bg-primary",
                sell: "bg-terminal-negative text-terminal-bg-primary",
                hold: "bg-terminal-warning text-terminal-bg-primary",
              }[r.action] || "bg-terminal-bg-tertiary text-terminal-text-primary";

              const confColor = {
                high: "text-terminal-positive",
                medium: "text-terminal-warning",
                low: "text-terminal-negative",
              }[r.confidence] || "text-terminal-text-tertiary";

              return (
                <div key={r.id} className="py-2 border-b border-terminal-border last:border-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${actionColor}`}>
                      {r.action}
                    </span>
                    <span className="font-mono text-sm text-terminal-text-primary">{r.ticker}</span>
                    <span className="text-xs text-terminal-text-secondary truncate">{r.securityName}</span>
                    <span className={`text-[10px] ml-auto ${confColor}`}>{r.confidence}</span>
                  </div>
                  <div className="text-xs text-terminal-text-tertiary line-clamp-2">
                    {r.rationale.length > 100 ? r.rationale.slice(0, 100) + "..." : r.rationale}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Panel 5: News Feed */}
        <div className="bg-terminal-bg-secondary rounded p-5 overflow-hidden flex flex-col">
          <div className="text-terminal-text-tertiary text-xs uppercase tracking-wider mb-3 flex items-center gap-2">
            <Newspaper size={14} />
            News Feed
          </div>
          <div className="flex-1 overflow-y-auto">
            {news.length === 0 && (
              <div className="text-terminal-text-tertiary text-sm">No news available</div>
            )}
            {news.map((n, i) => (
              <div
                key={n.id}
                className={`flex items-start gap-2.5 py-2 border-b border-terminal-border last:border-0 ${
                  i % 2 === 0 ? "" : "bg-terminal-bg-primary/20"
                }`}
              >
                <div className="w-1.5 h-1.5 rounded-full bg-terminal-text-tertiary mt-1.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-terminal-text-secondary leading-relaxed line-clamp-2">
                    {n.title}
                  </div>
                </div>
                <span className="text-[10px] font-mono text-terminal-text-tertiary shrink-0 mt-0.5">
                  {timeAgo(n.publishedAt)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Panel 6: Upcoming / Info */}
        <div className="bg-terminal-bg-secondary rounded p-5 overflow-hidden flex flex-col">
          <div className="text-terminal-text-tertiary text-xs uppercase tracking-wider mb-3 flex items-center gap-2">
            <Clock size={14} />
            Portfolio Snapshot
          </div>
          <div className="flex-1 overflow-y-auto space-y-3">
            {/* Quick stats */}
            {summary && (
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-terminal-text-secondary">Total Cost</span>
                  <span className="font-mono text-terminal-text-primary">
                    <Private>{formatCurrency(summary.totalCostEurCents)}</Private>
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-terminal-text-secondary">Market Value</span>
                  <span className="font-mono text-terminal-text-primary">
                    <Private>{formatCurrency(summary.totalValueEurCents)}</Private>
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-terminal-text-secondary">Unrealized P&L</span>
                  <span className={`font-mono ${summary.unrealizedPnlCents >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                    <Private>
                      {summary.unrealizedPnlCents >= 0 ? "+" : ""}{formatCurrency(summary.unrealizedPnlCents)}
                    </Private>
                  </span>
                </div>
                <div className="border-t border-terminal-border pt-2 mt-2">
                  <div className="text-xs text-terminal-text-tertiary uppercase tracking-wider mb-2">Top Holdings</div>
                  {[...holdings]
                    .sort((a, b) => b.marketValueEurCents - a.marketValueEurCents)
                    .slice(0, 5)
                    .map((h) => {
                      const totalVal = summary.totalValueEurCents || 1;
                      const weight = ((h.marketValueEurCents / totalVal) * 100);
                      return (
                        <div key={h.securityId} className="flex justify-between text-xs py-0.5">
                          <span className="font-mono text-terminal-text-primary">{h.ticker}</span>
                          <div className="flex gap-3">
                            <span className={`font-mono ${h.unrealizedPnlPct >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                              {h.unrealizedPnlPct >= 0 ? "+" : ""}{h.unrealizedPnlPct.toFixed(1)}%
                            </span>
                            <span className="font-mono text-terminal-text-secondary w-12 text-right">
                              {weight.toFixed(1)}%
                            </span>
                          </div>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}
          </div>

          {/* Last updated footer */}
          <div className="text-[10px] text-terminal-text-tertiary mt-2 pt-2 border-t border-terminal-border">
            Last updated: {lastUpdated?.toLocaleTimeString("fi-FI", { timeZone: "Europe/Helsinki" }) ?? "---"}
          </div>
        </div>
      </div>
    </div>
  );
}
