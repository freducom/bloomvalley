"use client";

import { useState, useEffect, useRef } from "react";
import { apiGet } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { Private } from "@/lib/privacy";
import { TickerLink } from "@/components/ui/TickerLink";

interface RiskMetrics {
  annualizedReturn: number;
  annualizedVolatility: number;
  sharpeRatio: number;
  sortinoRatio: number;
  maxDrawdown: number;
  var95Daily: number;
  var95DailyCents: number;
  beta: number;
  tradingDays: number;
  holdingsWithPriceData: number;
  holdingsTotal: number;
}

interface Position {
  ticker: string;
  name: string;
  assetClass: string;
  sector: string | null;
  valueCents: number;
  weight: number;
  breach: boolean;
}

interface ConcentrationAlert {
  type: string;
  severity: string;
  message: string;
}

interface Concentration {
  positions: Position[];
  sectors: { sector: string; weight: number; breach: boolean }[];
  assetClasses: { assetClass: string; weight: number }[];
  alerts: ConcentrationAlert[];
}

interface CorrelationMatrix {
  tickers: string[];
  matrix: number[][];
}

interface StressTest {
  id: string;
  name: string;
  description: string;
  impactCents: number;
  impactPct: number;
  portfolioAfterCents: number;
}

interface GlidepathCategory {
  category: string;
  current: number;
  target: number;
  drift: number;
}

interface Glidepath {
  currentAge: number;
  targetAge: number;
  categories: GlidepathCategory[];
  schedule: Record<string, number>[];
}

interface RiskData {
  metrics: RiskMetrics | null;
  concentration: Concentration | null;
  correlation: CorrelationMatrix | null;
  stressTests: StressTest[] | null;
  glidepath: Glidepath | null;
}

const CATEGORY_LABELS: Record<string, string> = {
  equity: "Equities",
  fixed_income: "Fixed Income",
  crypto: "Crypto",
  cash: "Cash",
};

export default function RiskPage() {
  const [data, setData] = useState<RiskData | null>(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState("1Y");

  useEffect(() => {
    setLoading(true);
    apiGet<RiskData>(`/risk?period=${period}`)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [period]);

  if (loading) {
    return (
      <div>
        <h1 className="text-3xl font-bold mb-6">Risk Analysis</h1>
        <div className="flex items-center justify-center h-64 text-terminal-text-secondary">
          Calculating risk metrics...
        </div>
      </div>
    );
  }

  if (!data || (!data.metrics && !data.concentration)) {
    return (
      <div>
        <h1 className="text-3xl font-bold mb-6">Risk Analysis</h1>
        <div className="flex items-center justify-center h-64 border border-terminal-border rounded-md bg-terminal-bg-secondary">
          <p className="text-terminal-text-secondary">Add holdings to view risk metrics.</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Risk Analysis</h1>
        <div className="flex gap-1 bg-terminal-bg-secondary rounded-lg p-1 border border-terminal-border">
          {["1Y", "2Y", "5Y"].map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1 text-sm rounded ${
                period === p
                  ? "bg-terminal-bg-tertiary text-terminal-text-primary"
                  : "text-terminal-text-secondary hover:text-terminal-text-primary"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Alerts */}
      {data.concentration?.alerts && data.concentration.alerts.length > 0 && (
        <div className="mb-6 space-y-2">
          {data.concentration.alerts.map((alert, i) => (
            <div
              key={i}
              className="flex items-center gap-2 px-4 py-2 rounded-lg border bg-yellow-900/20 border-yellow-700/50 text-yellow-400 text-sm"
            >
              <span className="font-mono text-xs uppercase">{alert.type}</span>
              <span>{alert.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* Key Metrics */}
      {data.metrics && <MetricsCards metrics={data.metrics} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        {/* Concentration */}
        {data.concentration && (
          <>
            <AssetAllocationCard concentration={data.concentration} />
            <TopPositionsCard positions={data.concentration.positions} />
            <SectorCard sectors={data.concentration.sectors} />
          </>
        )}

        {/* Correlation Heatmap */}
        {data.correlation && <CorrelationCard correlation={data.correlation} />}
      </div>

      {/* Stress Tests */}
      {data.stressTests && (
        <div className="mt-6">
          <StressTestCard tests={data.stressTests} />
        </div>
      )}

      {/* Glidepath */}
      {data.glidepath && (
        <div className="mt-6">
          <GlidepathCard glidepath={data.glidepath} />
        </div>
      )}
    </div>
  );
}

function MetricsCards({ metrics }: { metrics: RiskMetrics }) {
  const cards = [
    {
      label: "Ann. Return",
      value: formatPercent(metrics.annualizedReturn, true),
      color: metrics.annualizedReturn >= 0 ? "text-green-400" : "text-red-400",
    },
    {
      label: "Ann. Volatility",
      value: formatPercent(metrics.annualizedVolatility),
      color: metrics.annualizedVolatility > 25 ? "text-yellow-400" : "text-terminal-text-primary",
    },
    {
      label: "Sharpe Ratio",
      value: metrics.sharpeRatio.toFixed(2),
      color: metrics.sharpeRatio >= 1 ? "text-green-400" : metrics.sharpeRatio >= 0.5 ? "text-yellow-400" : "text-red-400",
    },
    {
      label: "Sortino Ratio",
      value: metrics.sortinoRatio.toFixed(2),
      color: metrics.sortinoRatio >= 1.5 ? "text-green-400" : metrics.sortinoRatio >= 0.7 ? "text-yellow-400" : "text-red-400",
    },
    {
      label: "Max Drawdown",
      value: formatPercent(metrics.maxDrawdown),
      color: metrics.maxDrawdown < -20 ? "text-red-400" : metrics.maxDrawdown < -10 ? "text-yellow-400" : "text-green-400",
    },
    {
      label: "VaR 95% (1-day)",
      value: <>{formatPercent(metrics.var95Daily)} / <Private>{formatCurrency(Math.abs(metrics.var95DailyCents))}</Private></>,
      color: "text-terminal-text-primary",
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {cards.map((c) => (
        <div key={c.label} className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-3">
          <div className="text-xs text-terminal-text-secondary mb-1">{c.label}</div>
          <div className={`text-lg font-mono font-bold ${c.color}`}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}

function AssetAllocationCard({ concentration }: { concentration: Concentration }) {
  const COLORS = ["#3B82F6", "#8B5CF6", "#F59E0B", "#22C55E", "#EF4444", "#6366F1", "#EC4899"];

  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4">
      <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">Asset Allocation</h3>
      <div className="space-y-2">
        {concentration.assetClasses.map((ac, i) => (
          <div key={ac.assetClass}>
            <div className="flex justify-between text-sm mb-1">
              <span className="capitalize">{ac.assetClass}</span>
              <span className="font-mono">{ac.weight.toFixed(1)}%</span>
            </div>
            <div className="h-2 bg-terminal-bg-tertiary rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${Math.min(ac.weight, 100)}%`, backgroundColor: COLORS[i % COLORS.length] }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TopPositionsCard({ positions }: { positions: Position[] }) {
  const top = positions.slice(0, 10);
  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4">
      <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">Top 10 Positions</h3>
      <div className="space-y-1.5">
        {top.map((p) => (
          <div key={p.ticker} className="flex items-center gap-2">
            <span className={`font-mono text-sm w-20 ${p.breach ? "text-yellow-400" : ""}`}>
              <TickerLink ticker={p.ticker} className={`font-mono hover:underline ${p.breach ? "text-yellow-400" : "text-terminal-accent"}`} />
            </span>
            <div className="flex-1 h-2 bg-terminal-bg-tertiary rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${p.breach ? "bg-yellow-400" : "bg-blue-500"}`}
                style={{ width: `${Math.min(p.weight * 2, 100)}%` }}
              />
            </div>
            <span className={`font-mono text-sm w-14 text-right ${p.breach ? "text-yellow-400" : ""}`}>
              {p.weight.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SectorCard({ sectors }: { sectors: { sector: string; weight: number; breach: boolean }[] }) {
  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4">
      <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">Sector Exposure</h3>
      <div className="space-y-1.5">
        {sectors.map((s) => (
          <div key={s.sector} className="flex items-center gap-2">
            <span className={`text-sm w-32 truncate ${s.breach ? "text-yellow-400" : ""}`}>
              {s.sector}
            </span>
            <div className="flex-1 h-2 bg-terminal-bg-tertiary rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${s.breach ? "bg-yellow-400" : "bg-purple-500"}`}
                style={{ width: `${Math.min(s.weight * 2, 100)}%` }}
              />
            </div>
            <span className={`font-mono text-sm w-14 text-right ${s.breach ? "text-yellow-400" : ""}`}>
              {s.weight.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CorrelationCard({ correlation }: { correlation: CorrelationMatrix }) {
  const { tickers, matrix } = correlation;

  const getColor = (val: number) => {
    if (val >= 0.8) return "bg-red-600/80";
    if (val >= 0.5) return "bg-red-600/40";
    if (val >= 0.2) return "bg-red-600/20";
    if (val >= -0.2) return "bg-gray-700/30";
    if (val >= -0.5) return "bg-blue-600/30";
    return "bg-blue-600/60";
  };

  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4 lg:col-span-2">
      <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">Correlation Matrix</h3>
      <div className="overflow-x-auto">
        <table className="text-xs">
          <thead>
            <tr>
              <th className="p-1" />
              {tickers.map((t) => (
                <th key={t} className="p-1 font-mono text-terminal-text-secondary -rotate-45 origin-bottom-left h-12">
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tickers.map((t, i) => (
              <tr key={t}>
                <td className="p-1 font-mono text-terminal-text-secondary whitespace-nowrap pr-2">{t}</td>
                {matrix[i].map((val, j) => (
                  <td key={j} className="p-0">
                    <div
                      className={`w-8 h-8 flex items-center justify-center font-mono ${getColor(val)} ${
                        i === j ? "opacity-50" : ""
                      }`}
                      title={`${tickers[i]} / ${tickers[j]}: ${val.toFixed(2)}`}
                    >
                      {i !== j ? (val > 0 ? val.toFixed(1) : val.toFixed(1)) : ""}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-4 mt-3 text-xs text-terminal-text-secondary">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-blue-600/60" /> Negative
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-gray-700/30" /> Low
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-red-600/40" /> Moderate
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded bg-red-600/80" /> High
        </span>
      </div>
    </div>
  );
}

function StressTestCard({ tests }: { tests: StressTest[] }) {
  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4">
      <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">Stress Tests</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {tests.map((t) => (
          <div key={t.id} className="bg-terminal-bg-tertiary rounded-lg p-3">
            <div className="text-sm font-medium mb-1">{t.name}</div>
            <div className="text-xs text-terminal-text-secondary mb-2">{t.description}</div>
            <div className="text-xl font-mono font-bold text-red-400">
              {t.impactPct > 0 ? "+" : ""}{t.impactPct.toFixed(1)}%
            </div>
            <div className="text-xs font-mono text-terminal-text-secondary mt-1">
              <Private>{formatCurrency(t.impactCents)}</Private> / After: <Private>{formatCurrency(t.portfolioAfterCents)}</Private>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function GlidepathCard({ glidepath }: { glidepath: Glidepath }) {
  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4">
      <h3 className="text-sm font-medium text-terminal-text-secondary mb-1">
        Glidepath — Age {glidepath.currentAge} → {glidepath.targetAge}
      </h3>
      <p className="text-xs text-terminal-text-secondary mb-4">
        Current allocation vs. target for fixed-income transition by age 60
      </p>

      {/* Current vs Target bars */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {glidepath.categories.map((cat) => {
          const label = CATEGORY_LABELS[cat.category] || cat.category;
          const driftColor =
            Math.abs(cat.drift) <= 3 ? "text-green-400" : Math.abs(cat.drift) <= 8 ? "text-yellow-400" : "text-red-400";
          return (
            <div key={cat.category} className="bg-terminal-bg-tertiary rounded-lg p-3">
              <div className="text-sm font-medium mb-2">{label}</div>
              <div className="flex items-end gap-3 h-16">
                <div className="flex-1 flex flex-col items-center">
                  <div className="text-xs text-terminal-text-secondary mb-1">Current</div>
                  <div className="w-full bg-terminal-bg-secondary rounded-full overflow-hidden h-4">
                    <div
                      className="h-full bg-blue-500 rounded-full"
                      style={{ width: `${Math.min(cat.current, 100)}%` }}
                    />
                  </div>
                  <div className="text-sm font-mono mt-1">{cat.current.toFixed(1)}%</div>
                </div>
                <div className="flex-1 flex flex-col items-center">
                  <div className="text-xs text-terminal-text-secondary mb-1">Target</div>
                  <div className="w-full bg-terminal-bg-secondary rounded-full overflow-hidden h-4">
                    <div
                      className="h-full bg-purple-500 rounded-full"
                      style={{ width: `${Math.min(cat.target, 100)}%` }}
                    />
                  </div>
                  <div className="text-sm font-mono mt-1">{cat.target.toFixed(1)}%</div>
                </div>
              </div>
              <div className={`text-center text-sm font-mono mt-2 ${driftColor}`}>
                {cat.drift > 0 ? "+" : ""}{cat.drift.toFixed(1)}% drift
              </div>
            </div>
          );
        })}
      </div>

      {/* Schedule table */}
      <h4 className="text-xs text-terminal-text-secondary mb-2">Target Schedule</h4>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-terminal-text-secondary text-left">
            <th className="pr-4 py-1 font-medium">Age</th>
            <th className="pr-4 py-1 font-medium text-right">Equity</th>
            <th className="pr-4 py-1 font-medium text-right">Fixed Income</th>
            <th className="pr-4 py-1 font-medium text-right">Crypto</th>
            <th className="py-1 font-medium text-right">Cash</th>
          </tr>
        </thead>
        <tbody>
          {glidepath.schedule.map((row) => (
            <tr
              key={row.age}
              className={row.age === glidepath.currentAge ? "text-blue-400 font-medium" : "text-terminal-text-secondary"}
            >
              <td className="pr-4 py-1 font-mono">{row.age}{row.age === glidepath.currentAge ? " (now)" : ""}</td>
              <td className="pr-4 py-1 font-mono text-right">{row.equity}%</td>
              <td className="pr-4 py-1 font-mono text-right">{row.fixed_income}%</td>
              <td className="pr-4 py-1 font-mono text-right">{row.crypto}%</td>
              <td className="py-1 font-mono text-right">{row.cash}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
