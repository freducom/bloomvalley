"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { apiGet, apiGetRaw, apiPost } from "@/lib/api";
import { TickerLink } from "@/components/ui/TickerLink";
import { formatCurrency, formatPercent } from "@/lib/format";
import { MetricCard } from "@/components/ui/MetricCard";
import { Private } from "@/lib/privacy";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

interface Recommendation {
  id: number;
  ticker: string;
  securityName: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: "high" | "medium" | "low";
  rationale: string;
}

interface Holding {
  accountId: number;
  accountName: string;
  accountType: string;
  securityId: number;
  ticker: string;
  name: string;
  assetClass: string;
  sector: string | null;
  quantity: string;
  avgCostCents: number;
  currentPriceCents: number | null;
  priceCurrency: string;
  priceDate: string | null;
  priceSource: string | null;
  marketValueCents: number | null;
  marketValueEurCents: number | null;
  costBasisEurCents: number | null;
  unrealizedPnlCents: number | null;
  unrealizedPnlPct: number | null;
  currency: string;
}

interface PortfolioSummary {
  totalValueEurCents: number;
  totalCostEurCents: number;
  totalCashEurCents: number;
  unrealizedPnlCents: number;
  unrealizedPnlPct: number | null;
  holdingsCount: number;
  allocation: Record<string, number>;
  accounts: {
    accountId: number;
    accountName: string;
    accountType: string;
    valueCents: number;
    cashBalanceCents: number;
    cashCurrency: string;
    holdingsCount: number;
  }[];
}

export default function PortfolioPage() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [sum, recRaw] = await Promise.all([
          apiGet<PortfolioSummary>("/portfolio/summary"),
          apiGetRaw<{ data: Recommendation[]; pagination: Record<string, unknown> }>(
            "/recommendations?status=active&limit=10"
          ).catch(() => ({ data: [] as Recommendation[], pagination: {} })),
        ]);
        setSummary(sum);
        setRecommendations(recRaw.data);
      } catch (e) {
        console.error("Failed to load portfolio:", e);
      } finally {
        setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 60000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="animate-pulse">
        <div className="h-8 bg-terminal-bg-secondary rounded w-48 mb-6" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-terminal-bg-secondary rounded" />
          ))}
        </div>
      </div>
    );
  }

  const isEmpty = !summary || summary.holdingsCount === 0;
  const pnlType =
    (summary?.unrealizedPnlCents ?? 0) > 0
      ? "positive"
      : (summary?.unrealizedPnlCents ?? 0) < 0
      ? "negative"
      : "neutral";

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Portfolio Dashboard</h1>
      </div>

      {/* Hero Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <MetricCard
          label="Total Value"
          value={<Private>{isEmpty ? "\u20AC0.00" : formatCurrency(summary!.totalValueEurCents)}</Private>}
          changeType="neutral"
        />
        <MetricCard
          label="Cost Basis"
          value={<Private>{isEmpty ? "\u20AC0.00" : formatCurrency(summary!.totalCostEurCents)}</Private>}
          changeType="neutral"
        />
        <MetricCard
          label="Unrealized P&L"
          value={
            <Private>{isEmpty
              ? "\u20AC0.00"
              : formatCurrency(summary!.unrealizedPnlCents)}</Private>
          }
          change={
            summary?.unrealizedPnlPct != null
              ? formatPercent(summary.unrealizedPnlPct, true)
              : undefined
          }
          changeType={pnlType as "positive" | "negative" | "neutral"}
        />
        <MetricCard
          label="Cash"
          value={
            <Private>{isEmpty
              ? "\u20AC0.00"
              : formatCurrency(summary!.totalCashEurCents)}</Private>
          }
          changeType="neutral"
        />
      </div>

      {isEmpty ? (
        <div className="flex items-center justify-center h-64 border border-terminal-border rounded-md bg-terminal-bg-secondary">
          <div className="text-center">
            <p className="text-lg text-terminal-text-secondary mb-2">
              No portfolio data yet
            </p>
            <p className="text-sm text-terminal-text-tertiary max-w-md">
              Import your Nordnet portfolio or add transactions to get started.
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Value History Chart */}
          <ValueHistoryChart />

          {/* Allocation */}
          <div>
            <h2 className="text-lg font-semibold mb-3">Asset Allocation</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {Object.entries(summary!.allocation).map(([ac, cents]) => {
                const pct =
                  summary!.totalValueEurCents > 0
                    ? ((cents / summary!.totalValueEurCents) * 100).toFixed(1)
                    : "0.0";
                return (
                  <div
                    key={ac}
                    className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-3"
                  >
                    <div className="text-xs text-terminal-text-secondary font-mono uppercase">
                      {ac}
                    </div>
                    <div className="text-lg font-mono font-semibold mt-1">
                      <Private>{formatCurrency(cents)}</Private>
                    </div>
                    <div className="text-sm text-terminal-text-tertiary font-mono">
                      <Private>{pct}%</Private>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Accounts */}
          <div>
            <h2 className="text-lg font-semibold mb-3">Accounts</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {summary!.accounts.map((acct) => (
                <div
                  key={acct.accountId}
                  className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">
                      {acct.accountName}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded bg-terminal-info/20 text-terminal-info font-mono">
                      {acct.accountType}
                    </span>
                  </div>
                  <div className="text-lg font-mono font-semibold mt-1">
                    <Private>{formatCurrency(acct.valueCents)}</Private>
                  </div>
                  <div className="text-xs text-terminal-text-tertiary">
                    {acct.holdingsCount} holding
                    {acct.holdingsCount !== 1 ? "s" : ""}
                    {acct.cashBalanceCents > 0 && (
                      <span className="ml-2">
                        Cash: <Private>{formatCurrency(acct.cashBalanceCents, acct.cashCurrency)}</Private>
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Recommendations */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold">Recommendations</h2>
              <Link
                href="/recommendations"
                className="text-sm text-terminal-accent hover:underline font-mono"
              >
                View all &rarr;
              </Link>
            </div>
            {recommendations.length === 0 ? (
              <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4 text-sm text-terminal-text-tertiary">
                No active recommendations
              </div>
            ) : (
              <div className="border border-terminal-border rounded-md divide-y divide-terminal-border">
                {recommendations.map((rec) => (
                  <div
                    key={rec.id}
                    className="flex items-center gap-3 px-4 py-2 bg-terminal-bg-secondary hover:bg-terminal-bg-secondary/70 transition-colors"
                  >
                    <span
                      className={`text-xs font-mono font-semibold px-2 py-0.5 rounded ${
                        rec.action === "BUY"
                          ? "bg-terminal-positive/20 text-terminal-positive"
                          : rec.action === "SELL"
                          ? "bg-terminal-negative/20 text-terminal-negative"
                          : "bg-terminal-warning/20 text-terminal-warning"
                      }`}
                    >
                      {rec.action}
                    </span>
                    <TickerLink ticker={rec.ticker} className="font-mono text-sm text-terminal-accent whitespace-nowrap hover:underline" />
                    <span className="text-sm text-terminal-text-secondary truncate flex-1 min-w-0">
                      {rec.rationale.length > 100
                        ? rec.rationale.slice(0, 100) + "\u2026"
                        : rec.rationale}
                    </span>
                    <span
                      className={`text-xs font-mono px-2 py-0.5 rounded whitespace-nowrap ${
                        rec.confidence === "high"
                          ? "bg-terminal-positive/20 text-terminal-positive"
                          : rec.confidence === "medium"
                          ? "bg-terminal-warning/20 text-terminal-warning"
                          : "bg-terminal-text-tertiary/20 text-terminal-text-tertiary"
                      }`}
                    >
                      {rec.confidence}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Brinson Attribution */}
          <BrinsonAttribution />
        </div>
      )}
    </div>
  );
}

/* ── Portfolio Value History Chart ── */

interface ValuePoint {
  date: string;
  valueCents: number;
  dividendCents?: number;
}

interface DividendItem {
  ticker: string;
  grossCents: number;
  netCents: number;
  currency: string;
}

interface DividendAnnotation {
  date: string;
  totalNetCents: number;
  items: DividendItem[];
}

const PERIOD_OPTIONS = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
  { label: "2Y", days: 730 },
];

function ValueHistoryChart() {
  const [data, setData] = useState<ValuePoint[]>([]);
  const [dividends, setDividends] = useState<DividendAnnotation[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(90);

  useEffect(() => {
    setLoading(true);
    apiGetRaw<{ data: ValuePoint[]; dividends?: DividendAnnotation[] }>(
      `/portfolio/value-history?days=${days}`
    )
      .then((res) => {
        // Merge dividend data into chart points for tooltip display
        const divMap = new Map<string, DividendAnnotation>();
        for (const d of res.dividends || []) {
          divMap.set(d.date, d);
        }
        const merged = res.data.map((p) => ({
          ...p,
          dividendCents: divMap.get(p.date)?.totalNetCents || undefined,
        }));
        setData(merged);
        setDividends(res.dividends || []);
      })
      .catch(() => {
        setData([]);
        setDividends([]);
      })
      .finally(() => setLoading(false));
  }, [days]);

  if (loading) {
    return (
      <div>
        <h2 className="text-lg font-semibold mb-3">Portfolio Value</h2>
        <div className="h-64 bg-terminal-bg-secondary rounded animate-pulse" />
      </div>
    );
  }

  if (data.length < 2) {
    return null;
  }

  const first = data[0].valueCents;
  const last = data[data.length - 1].valueCents;
  const changePositive = last >= first;

  const formatAxis = (cents: number) => {
    const v = cents / 100;
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(0)}k`;
    return v.toFixed(0);
  };

  const formatTooltipValue = (cents: number) => formatCurrency(cents);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Portfolio Value</h2>
        <div className="flex gap-1">
          {PERIOD_OPTIONS.map((p) => (
            <button
              key={p.days}
              onClick={() => setDays(p.days)}
              className={`px-2 py-1 text-xs font-mono rounded transition-colors ${
                days === p.days
                  ? "bg-terminal-accent/20 text-terminal-accent border border-terminal-accent/50"
                  : "text-terminal-text-secondary border border-terminal-border hover:text-terminal-text-primary"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <Private>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={data} margin={{ top: 5, right: 5, bottom: 0, left: 5 }}>
              <defs>
                <linearGradient id="valueGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor={changePositive ? "#22c55e" : "#ef4444"}
                    stopOpacity={0.3}
                  />
                  <stop
                    offset="100%"
                    stopColor={changePositive ? "#22c55e" : "#ef4444"}
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "#6b7280" }}
                tickFormatter={(d: string) => {
                  const dt = new Date(d);
                  return `${dt.getDate()}/${dt.getMonth() + 1}`;
                }}
                axisLine={false}
                tickLine={false}
                minTickGap={40}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "#6b7280" }}
                tickFormatter={formatAxis}
                axisLine={false}
                tickLine={false}
                width={50}
                domain={["dataMin", "dataMax"]}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1a1f2e",
                  border: "1px solid #2d3548",
                  borderRadius: "4px",
                  fontSize: "12px",
                }}
                labelStyle={{ color: "#9ca3af" }}
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  const point = payload[0]?.payload as ValuePoint;
                  const dt = new Date(label);
                  const dateStr = dt.toLocaleDateString("en-GB", {
                    day: "numeric", month: "short", year: "numeric",
                  });
                  const divAnnotation = dividends.find((d) => d.date === point.date);
                  return (
                    <div style={{
                      backgroundColor: "#1a1f2e",
                      border: "1px solid #2d3548",
                      borderRadius: "4px",
                      padding: "8px 12px",
                      fontSize: "12px",
                    }}>
                      <div style={{ color: "#9ca3af", marginBottom: 4 }}>{dateStr}</div>
                      <div style={{ color: "#e5e7eb" }}>
                        Value: {formatTooltipValue(point.valueCents)}
                      </div>
                      {divAnnotation && (
                        <div style={{ marginTop: 6, borderTop: "1px solid #2d3548", paddingTop: 4 }}>
                          <div style={{ color: "#a78bfa", fontWeight: 600, marginBottom: 2 }}>
                            Dividend received
                          </div>
                          {divAnnotation.items.map((item, i) => (
                            <div key={i} style={{ color: "#c4b5fd" }}>
                              {item.ticker}: {formatCurrency(item.netCents)} net
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                }}
              />
              {dividends.map((d) => (
                <ReferenceLine
                  key={d.date}
                  x={d.date}
                  stroke="#a78bfa"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                  label={{
                    value: "D",
                    position: "top",
                    fill: "#a78bfa",
                    fontSize: 9,
                    fontWeight: 600,
                  }}
                />
              ))}
              <Area
                type="monotone"
                dataKey="valueCents"
                stroke={changePositive ? "#22c55e" : "#ef4444"}
                strokeWidth={1.5}
                fill="url(#valueGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </Private>
      </div>
    </div>
  );
}

/* ── Brinson Return Attribution ── */

interface AttributionRow {
  group: string;
  portfolioWeight: number;
  benchmarkWeight: number;
  portfolioReturn: number;
  benchmarkReturn: number;
  allocationEffect: number;
  selectionEffect: number;
  interactionEffect: number;
  activeReturn: number;
  holdings: number;
}

interface AttributionData {
  attribution: AttributionRow[];
  summary: {
    portfolioReturn: number;
    benchmarkReturn: number;
    activeReturn: number;
    allocationEffect: number;
    selectionEffect: number;
    interactionEffect: number;
  };
  benchmark: { ticker: string | null; found: boolean };
  period: { from: string; to: string };
  groupBy: string;
}

function BrinsonAttribution() {
  const [data, setData] = useState<AttributionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<"sector" | "assetClass">("sector");
  const [snapshotting, setSnapshotting] = useState(false);
  const [hasFetched, setHasFetched] = useState(false);

  const today = new Date().toISOString().split("T")[0];
  const [fromDate, setFromDate] = useState(today);
  const [toDate, setToDate] = useState(today);

  const fetchAttribution = useCallback(async () => {
    if (fromDate >= toDate) {
      setError("Select a date range where 'from' is before 'to'.");
      setData(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiGetRaw<{ data: AttributionData }>(
        `/attribution/brinson?from=${fromDate}&to=${toDate}&groupBy=${groupBy}`
      );
      setData(res.data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load attribution";
      if (msg.includes("snapshot") || msg.includes("404")) {
        setError("No holdings snapshot found for this date range. Click \"Snapshot\" to capture today's holdings, then select a valid range.");
      } else if (msg.includes("from must be before to")) {
        setError("Select a date range where 'from' is before 'to'.");
      } else {
        setError(msg);
      }
      setData(null);
    } finally {
      setLoading(false);
      setHasFetched(true);
    }
  }, [fromDate, toDate, groupBy]);

  // Don't auto-fetch — wait for user to set dates or take a snapshot
  // Only auto-fetch if dates are valid (from < to)

  const takeSnapshot = async () => {
    setSnapshotting(true);
    try {
      await apiPost("/portfolio/snapshot");
      fetchAttribution();
    } catch { /* */ }
    finally { setSnapshotting(false); }
  };

  const fmtPct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
  const colorPct = (v: number) => v > 0 ? "text-terminal-positive" : v < 0 ? "text-terminal-negative" : "text-terminal-text-tertiary";

  return (
    <div className="mt-8">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">Return Attribution (Brinson)</h2>
          <span className="relative group">
            <span className="inline-flex items-center justify-center w-4 h-4 rounded-full border border-terminal-text-tertiary text-terminal-text-tertiary text-[10px] cursor-help leading-none">i</span>
            <span className="absolute left-6 top-0 z-10 hidden group-hover:block w-72 p-2 text-xs text-terminal-text-primary bg-terminal-bg-tertiary border border-terminal-border rounded shadow-md">
              Brinson-Fachler attribution decomposes your portfolio&apos;s return vs. a benchmark into three effects: <strong>Allocation</strong> (over/underweighting sectors), <strong>Selection</strong> (picking better/worse securities within sectors), and <strong>Interaction</strong> (the combined effect of both decisions).
            </span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
            className="bg-terminal-bg-secondary border border-terminal-border rounded px-2 py-1 text-xs font-mono" />
          <span className="text-terminal-text-tertiary text-xs">to</span>
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
            className="bg-terminal-bg-secondary border border-terminal-border rounded px-2 py-1 text-xs font-mono" />
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value as "sector" | "assetClass")}
            className="bg-terminal-bg-secondary border border-terminal-border rounded px-2 py-1 text-xs">
            <option value="sector">By Sector</option>
            <option value="assetClass">By Asset Class</option>
          </select>
          <button onClick={fetchAttribution} disabled={loading || fromDate >= toDate}
            className="px-2 py-1 text-xs font-mono bg-terminal-accent/20 text-terminal-accent border border-terminal-accent/50 rounded hover:bg-terminal-accent/30 disabled:opacity-40">
            {loading ? "..." : "Run"}
          </button>
          <button onClick={takeSnapshot} disabled={snapshotting}
            className="px-2 py-1 text-xs font-mono border border-terminal-border text-terminal-text-secondary rounded hover:text-terminal-accent hover:border-terminal-accent disabled:opacity-40">
            {snapshotting ? "..." : "Snapshot"}
          </button>
        </div>
      </div>

      {!hasFetched && !loading && !data && !error && (
        <div className="text-sm text-terminal-text-tertiary bg-terminal-bg-secondary border border-terminal-border rounded p-4">
          Select a date range and click Run. Take a Snapshot first to capture today&apos;s holdings.
        </div>
      )}

      {error && (
        <div className="text-sm text-terminal-warning bg-terminal-warning/10 border border-terminal-warning/20 rounded p-3 mb-3">
          {error}
        </div>
      )}

      {loading ? (
        <div className="h-32 bg-terminal-bg-secondary rounded animate-pulse" />
      ) : data ? (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mb-4">
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-2">
              <div className="text-xs text-terminal-text-tertiary">Portfolio</div>
              <div className={`text-sm font-mono font-bold ${colorPct(data.summary.portfolioReturn)}`}>{fmtPct(data.summary.portfolioReturn)}</div>
            </div>
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-2">
              <div className="text-xs text-terminal-text-tertiary">Benchmark{data.benchmark.ticker ? ` (${data.benchmark.ticker})` : ""}</div>
              <div className={`text-sm font-mono font-bold ${colorPct(data.summary.benchmarkReturn)}`}>{fmtPct(data.summary.benchmarkReturn)}</div>
            </div>
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-2">
              <div className="text-xs text-terminal-text-tertiary">Active Return</div>
              <div className={`text-sm font-mono font-bold ${colorPct(data.summary.activeReturn)}`}>{fmtPct(data.summary.activeReturn)}</div>
            </div>
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-2">
              <div className="text-xs text-terminal-text-tertiary">Allocation</div>
              <div className={`text-sm font-mono font-bold ${colorPct(data.summary.allocationEffect)}`}>{fmtPct(data.summary.allocationEffect)}</div>
            </div>
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-2">
              <div className="text-xs text-terminal-text-tertiary">Selection</div>
              <div className={`text-sm font-mono font-bold ${colorPct(data.summary.selectionEffect)}`}>{fmtPct(data.summary.selectionEffect)}</div>
            </div>
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-2">
              <div className="text-xs text-terminal-text-tertiary">Interaction</div>
              <div className={`text-sm font-mono font-bold ${colorPct(data.summary.interactionEffect)}`}>{fmtPct(data.summary.interactionEffect)}</div>
            </div>
          </div>

          {/* Attribution table */}
          <div className="border border-terminal-border rounded-md overflow-x-auto">
            <table className="w-full text-sm min-w-[700px]">
              <thead>
                <tr className="bg-terminal-bg-secondary text-terminal-text-secondary text-xs">
                  <th className="text-left px-3 py-2 font-medium">{groupBy === "sector" ? "Sector" : "Asset Class"}</th>
                  <th className="text-right px-3 py-2 font-medium">Wt (P)</th>
                  <th className="text-right px-3 py-2 font-medium">Wt (B)</th>
                  <th className="text-right px-3 py-2 font-medium">Ret (P)</th>
                  <th className="text-right px-3 py-2 font-medium">Ret (B)</th>
                  <th className="text-right px-3 py-2 font-medium">Allocation</th>
                  <th className="text-right px-3 py-2 font-medium">Selection</th>
                  <th className="text-right px-3 py-2 font-medium">Interaction</th>
                  <th className="text-right px-3 py-2 font-medium">Active</th>
                  <th className="text-right px-3 py-2 font-medium">#</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-terminal-border">
                {data.attribution.map((a) => (
                  <tr key={a.group} className="hover:bg-terminal-bg-secondary/50">
                    <td className="px-3 py-2 font-medium">{a.group}</td>
                    <td className="px-3 py-2 text-right font-mono">{a.portfolioWeight.toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono text-terminal-text-tertiary">{a.benchmarkWeight.toFixed(1)}%</td>
                    <td className={`px-3 py-2 text-right font-mono ${colorPct(a.portfolioReturn)}`}>{fmtPct(a.portfolioReturn)}</td>
                    <td className={`px-3 py-2 text-right font-mono text-terminal-text-tertiary`}>{fmtPct(a.benchmarkReturn)}</td>
                    <td className={`px-3 py-2 text-right font-mono ${colorPct(a.allocationEffect)}`}>{fmtPct(a.allocationEffect)}</td>
                    <td className={`px-3 py-2 text-right font-mono ${colorPct(a.selectionEffect)}`}>{fmtPct(a.selectionEffect)}</td>
                    <td className={`px-3 py-2 text-right font-mono ${colorPct(a.interactionEffect)}`}>{fmtPct(a.interactionEffect)}</td>
                    <td className={`px-3 py-2 text-right font-mono font-medium ${colorPct(a.activeReturn)}`}>{fmtPct(a.activeReturn)}</td>
                    <td className="px-3 py-2 text-right text-terminal-text-tertiary">{a.holdings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
