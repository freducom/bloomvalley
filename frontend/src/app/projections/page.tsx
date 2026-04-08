"use client";

import { useState, useEffect, useCallback } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  LineChart,
  Line,
  CartesianGrid,
} from "recharts";
import { MetricCard } from "@/components/ui/MetricCard";
import { InfoTip } from "@/components/ui/InfoTip";
import { Private } from "@/lib/privacy";
import { formatCurrency, formatLargeNumber, formatPercent } from "@/lib/format";
import { apiGetRaw } from "@/lib/api";

/* ── Types ── */

interface FanChartPoint {
  age: number;
  year: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

interface ProjectionSummary {
  medianAtRetirement: number;
  meanAtRetirement: number;
  p5AtRetirement: number;
  p25AtRetirement: number;
  p75AtRetirement: number;
  p95AtRetirement: number;
  probabilityOfTarget: number;
  targetValue: number;
  safeWithdrawalRate: number;
  probabilityLastingTo85: number;
  probabilityLastingTo90: number;
  probabilityLastingTo95: number;
}

interface ProjectionParams {
  currentPortfolioValue: number;
  annualContribution: number;
  contributionGrowth: number;
  retirementAge: number;
  withdrawalRate: number;
  numPaths: number;
  expectedReturns: {
    equities: number;
    fixedIncome: number;
    crypto: number;
    cash: number;
  };
}

interface ProjectionResponse {
  params: ProjectionParams;
  fanChart: FanChartPoint[];
  summary: ProjectionSummary;
}

interface SensitivityPoint {
  inputValue: number;
  outputValue: number;
}

interface SensitivityResponse {
  variable: string;
  outputMetric: string;
  baseline: SensitivityPoint;
  dataPoints: SensitivityPoint[];
}

/* ── Constants ── */

const SENSITIVITY_VARIABLES = [
  { key: "equityReturn", label: "Equity Return" },
  { key: "annualContribution", label: "Annual Contribution" },
  { key: "retirementAge", label: "Retirement Age" },
  { key: "withdrawalRate", label: "Withdrawal Rate" },
] as const;

/* ── Helpers ── */

function fmtAge(age: number): string {
  return `${age}`;
}

function fmtAxisCents(cents: number): string {
  const eur = cents / 100;
  if (eur >= 1_000_000) return `${(eur / 1_000_000).toFixed(1)}M`;
  if (eur >= 1_000) return `${(eur / 1_000).toFixed(0)}k`;
  return `${eur.toFixed(0)}`;
}

function fmtSensitivityInput(variable: string, val: number): string {
  if (variable === "annualContribution") return formatLargeNumber(val);
  if (variable === "equityReturn" || variable === "withdrawalRate")
    return formatPercent(val * 100);
  if (variable === "retirementAge") return `${val}`;
  return `${val}`;
}

function fmtSensitivityOutput(metric: string, val: number): string {
  if (metric === "medianAtRetirement" || metric === "p5AtRetirement")
    return formatLargeNumber(val);
  return formatPercent(val * 100);
}

/* ── Custom Tooltip ── */

function FanChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as FanChartPoint | undefined;
  if (!d) return null;

  return (
    <div className="bg-terminal-bg-tertiary border border-terminal-border rounded-md p-3 text-xs font-mono shadow-lg">
      <div className="text-terminal-text-secondary mb-2">Age {d.age} (Year {d.year})</div>
      <div className="space-y-1">
        <div className="flex justify-between gap-4">
          <span className="text-terminal-text-tertiary">P95 (optimistic)</span>
          <Private><span className="text-terminal-positive">{formatLargeNumber(d.p95)}</span></Private>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-terminal-text-tertiary">P75</span>
          <Private><span className="text-terminal-text-primary">{formatLargeNumber(d.p75)}</span></Private>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-terminal-text-tertiary">P50 (median)</span>
          <Private><span className="text-terminal-accent">{formatLargeNumber(d.p50)}</span></Private>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-terminal-text-tertiary">P25</span>
          <Private><span className="text-terminal-text-primary">{formatLargeNumber(d.p25)}</span></Private>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-terminal-text-tertiary">P5 (pessimistic)</span>
          <Private><span className="text-terminal-negative">{formatLargeNumber(d.p5)}</span></Private>
        </div>
      </div>
    </div>
  );
}

/* ── Page Component ── */

export default function ProjectionsPage() {
  // Simulation params
  const [annualContribution, setAnnualContribution] = useState(24000);
  const [contributionGrowth, setContributionGrowth] = useState(2);
  const [withdrawalRate, setWithdrawalRate] = useState(4);
  const [retirementAge, setRetirementAge] = useState(60);

  // Data
  const [data, setData] = useState<ProjectionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Sensitivity
  const [sensVariable, setSensVariable] = useState("equityReturn");
  const [sensData, setSensData] = useState<SensitivityResponse | null>(null);
  const [sensLoading, setSensLoading] = useState(false);

  // Fan chart phase toggle
  const [showPhase, setShowPhase] = useState<"all" | "accumulation" | "withdrawal">("all");

  const loadProjection = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        annualContribution: String(annualContribution * 100),
        contributionGrowth: String(contributionGrowth / 100),
        withdrawalRate: String(withdrawalRate / 100),
        retirementAge: String(retirementAge),
        numPaths: "10000",
      });
      const res = await apiGetRaw<ProjectionResponse>(
        `/projections/monte-carlo?${qs}`
      );
      setData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load projection");
    } finally {
      setLoading(false);
    }
  }, [annualContribution, contributionGrowth, withdrawalRate, retirementAge]);

  const loadSensitivity = useCallback(async () => {
    setSensLoading(true);
    try {
      const qs = new URLSearchParams({
        variable: sensVariable,
        outputMetric: "medianAtRetirement",
      });
      const res = await apiGetRaw<SensitivityResponse>(
        `/projections/sensitivity?${qs}`
      );
      setSensData(res);
    } catch {
      setSensData(null);
    } finally {
      setSensLoading(false);
    }
  }, [sensVariable]);

  useEffect(() => {
    loadProjection();
  }, [loadProjection]);

  useEffect(() => {
    loadSensitivity();
  }, [loadSensitivity]);

  // Filter fan chart by phase
  const filteredFanChart = data?.fanChart.filter((p) => {
    if (showPhase === "all") return true;
    if (showPhase === "accumulation") return p.age <= retirementAge;
    return p.age >= retirementAge;
  }) ?? [];

  /* ── Loading skeleton ── */
  if (loading && !data) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <h1 className="text-2xl font-bold text-terminal-text-primary mb-6">
          Retirement Projections
        </h1>
        <div className="animate-pulse space-y-6">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-[88px] bg-terminal-bg-secondary rounded-md" />
            ))}
          </div>
          <div className="h-[400px] bg-terminal-bg-secondary rounded-md" />
        </div>
      </div>
    );
  }

  const s = data?.summary;
  const p = data?.params;

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-terminal-text-primary">
            Retirement Projections
          </h1>
          <p className="text-sm text-terminal-text-secondary mt-1">
            Monte Carlo simulation &mdash; 10,000 paths with correlated asset returns, glidepath rebalancing, and tax drag
          </p>
        </div>
        {p && (
          <div className="text-xs font-mono text-terminal-text-tertiary">
            Portfolio: <Private>{formatLargeNumber(p.currentPortfolioValue)}</Private>
          </div>
        )}
      </div>

      {error && (
        <div className="text-sm text-terminal-warning bg-terminal-warning/10 border border-terminal-warning/20 rounded p-3">
          {error}
        </div>
      )}

      {/* ── Input Controls ── */}
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">
          Simulation Parameters
        </h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="block text-xs text-terminal-text-tertiary mb-1">
              Annual Contribution (EUR)
            </label>
            <input
              type="number"
              value={annualContribution}
              onChange={(e) => setAnnualContribution(Number(e.target.value))}
              className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-3 py-2 text-sm font-mono text-terminal-text-primary focus:border-terminal-accent focus:outline-none"
              min={0}
              step={1000}
            />
          </div>
          <div>
            <label className="block text-xs text-terminal-text-tertiary mb-1">
              Contribution Growth (%/yr)
            </label>
            <input
              type="number"
              value={contributionGrowth}
              onChange={(e) => setContributionGrowth(Number(e.target.value))}
              className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-3 py-2 text-sm font-mono text-terminal-text-primary focus:border-terminal-accent focus:outline-none"
              min={0}
              max={20}
              step={0.5}
            />
          </div>
          <div>
            <label className="block text-xs text-terminal-text-tertiary mb-1">
              Withdrawal Rate (%)
            </label>
            <input
              type="number"
              value={withdrawalRate}
              onChange={(e) => setWithdrawalRate(Number(e.target.value))}
              className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-3 py-2 text-sm font-mono text-terminal-text-primary focus:border-terminal-accent focus:outline-none"
              min={1}
              max={10}
              step={0.5}
            />
          </div>
          <div>
            <label className="block text-xs text-terminal-text-tertiary mb-1">
              Retirement Age
            </label>
            <input
              type="number"
              value={retirementAge}
              onChange={(e) => setRetirementAge(Number(e.target.value))}
              className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-3 py-2 text-sm font-mono text-terminal-text-primary focus:border-terminal-accent focus:outline-none"
              min={50}
              max={70}
              step={1}
            />
          </div>
        </div>
        <div className="mt-3 flex justify-end">
          <button
            onClick={loadProjection}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium rounded bg-terminal-accent/20 text-terminal-accent border border-terminal-accent/50 hover:bg-terminal-accent/30 transition-colors disabled:opacity-50"
          >
            {loading ? "Simulating..." : "Run Simulation"}
          </button>
        </div>
      </div>

      {/* ── Summary Metrics ── */}
      {s && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard
            label="Median at Retirement"
            value={<Private>{formatLargeNumber(s.medianAtRetirement)}</Private>}
            change={`P5: ${formatLargeNumber(s.p5AtRetirement)}`}
            changeType="neutral"
          />
          <MetricCard
            label={<>P(Reaching Target) <InfoTip text="Monte Carlo simulation result showing the likelihood of reaching your target portfolio value, based on thousands of randomized return scenarios." /></>}
            value={formatPercent(s.probabilityOfTarget * 100)}
            change={`Target: ${formatLargeNumber(s.targetValue)}`}
            changeType={s.probabilityOfTarget >= 0.5 ? "positive" : "negative"}
          />
          <MetricCard
            label={<>Safe Withdrawal Rate <InfoTip text="The maximum percentage you can withdraw annually from your portfolio without running out of money over a given timeframe. The classic '4% rule' is based on historical US market returns." /></>}
            value={formatPercent(s.safeWithdrawalRate * 100)}
            change="95% survival to age 95"
            changeType={s.safeWithdrawalRate >= 0.035 ? "positive" : "neutral"}
          />
          <MetricCard
            label={<>P(Lasting to 90) <InfoTip text="Likelihood that your portfolio survives to the target age given planned withdrawals. Based on Monte Carlo simulation with historical return distributions." /></>}
            value={formatPercent(s.probabilityLastingTo90 * 100)}
            change={`To 95: ${formatPercent(s.probabilityLastingTo95 * 100)}`}
            changeType={s.probabilityLastingTo90 >= 0.85 ? "positive" : "negative"}
          />
        </div>
      )}

      {/* ── Fan Chart ── */}
      {data && (
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-terminal-text-secondary">
              Portfolio Value Projection <InfoTip text="Confidence bands from Monte Carlo simulation. P50 is the median outcome; P5/P95 show the 5th/95th percentile (worst/best 5% of scenarios)." />
            </h3>
            <div className="flex gap-1">
              {(["all", "accumulation", "withdrawal"] as const).map((phase) => (
                <button
                  key={phase}
                  onClick={() => setShowPhase(phase)}
                  className={`px-2 py-1 text-xs font-mono rounded transition-colors capitalize ${
                    showPhase === phase
                      ? "bg-terminal-accent/20 text-terminal-accent border border-terminal-accent/50"
                      : "text-terminal-text-secondary border border-terminal-border hover:text-terminal-text-primary"
                  }`}
                >
                  {phase}
                </button>
              ))}
            </div>
          </div>

          <ResponsiveContainer width="100%" height={400}>
            <AreaChart
              data={filteredFanChart}
              margin={{ top: 10, right: 10, bottom: 0, left: 10 }}
            >
              <defs>
                <linearGradient id="p5p95" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#8B5CF6" stopOpacity={0.08} />
                  <stop offset="100%" stopColor="#8B5CF6" stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="p25p75" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#8B5CF6" stopOpacity={0.2} />
                  <stop offset="100%" stopColor="#8B5CF6" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
              <XAxis
                dataKey="age"
                tick={{ fontSize: 11, fill: "#6B7280" }}
                tickFormatter={fmtAge}
                label={{ value: "Age", position: "insideBottom", offset: -2, fontSize: 11, fill: "#6B7280" }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#6B7280" }}
                tickFormatter={fmtAxisCents}
                width={60}
              />
              <Tooltip content={<FanChartTooltip />} />

              {/* Retirement age reference line */}
              <ReferenceLine
                x={retirementAge}
                stroke="#F59E0B"
                strokeDasharray="4 4"
                label={{
                  value: "Retirement",
                  position: "top",
                  fontSize: 10,
                  fill: "#F59E0B",
                }}
              />

              {/* P5-P95 band */}
              <Area
                type="monotone"
                dataKey="p95"
                stroke="none"
                fill="url(#p5p95)"
                fillOpacity={1}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="p5"
                stroke="none"
                fill="#0A0E17"
                fillOpacity={1}
                isAnimationActive={false}
              />

              {/* P25-P75 band */}
              <Area
                type="monotone"
                dataKey="p75"
                stroke="none"
                fill="url(#p25p75)"
                fillOpacity={1}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="p25"
                stroke="none"
                fill="#0A0E17"
                fillOpacity={1}
                isAnimationActive={false}
              />

              {/* Median line */}
              <Area
                type="monotone"
                dataKey="p50"
                stroke="#8B5CF6"
                strokeWidth={2}
                fill="none"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>

          {/* Legend */}
          <div className="flex items-center justify-center gap-6 mt-3 text-xs text-terminal-text-tertiary">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-[#8B5CF6]/10 border border-[#8B5CF6]/30" />
              P5&ndash;P95
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-[#8B5CF6]/25 border border-[#8B5CF6]/50" />
              P25&ndash;P75
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-8 h-0.5 bg-[#8B5CF6]" />
              Median
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-8 h-0.5 border-t-2 border-dashed border-[#F59E0B]" />
              Retirement
            </span>
          </div>
        </div>
      )}

      {/* ── Bottom Grid: Survival + Percentiles + Sensitivity ── */}
      {s && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Survival Probabilities */}
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
            <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">
              Survival Probabilities <InfoTip text="Likelihood that your portfolio survives to the target age given planned withdrawals. Based on Monte Carlo simulation with historical return distributions." />
            </h3>
            <div className="space-y-3">
              {[
                { label: "Lasting to 85", prob: s.probabilityLastingTo85 },
                { label: "Lasting to 90", prob: s.probabilityLastingTo90 },
                { label: "Lasting to 95", prob: s.probabilityLastingTo95 },
              ].map(({ label, prob }) => (
                <div key={label}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-terminal-text-tertiary">{label}</span>
                    <span
                      className={`font-mono ${
                        prob >= 0.9
                          ? "text-terminal-positive"
                          : prob >= 0.75
                          ? "text-terminal-warning"
                          : "text-terminal-negative"
                      }`}
                    >
                      {formatPercent(prob * 100)}
                    </span>
                  </div>
                  <div className="h-2 bg-terminal-bg-primary rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${
                        prob >= 0.9
                          ? "bg-terminal-positive"
                          : prob >= 0.75
                          ? "bg-terminal-warning"
                          : "bg-terminal-negative"
                      }`}
                      style={{ width: `${prob * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-terminal-border">
              <div className="flex justify-between text-xs">
                <span className="text-terminal-text-tertiary">Safe Withdrawal Rate <InfoTip text="The maximum percentage you can withdraw annually from your portfolio without running out of money over a given timeframe. The classic '4% rule' is based on historical US market returns." /></span>
                <span className="font-mono text-terminal-accent font-semibold">
                  {formatPercent(s.safeWithdrawalRate * 100)}
                </span>
              </div>
              <p className="text-[10px] text-terminal-text-tertiary mt-1">
                Maximum rate where P(lasting to 95) &ge; 95%
              </p>
            </div>
          </div>

          {/* Retirement Distribution */}
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
            <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">
              Portfolio at Retirement
            </h3>
            <div className="space-y-2">
              {[
                { label: "P95 (optimistic)", value: s.p95AtRetirement, color: "text-terminal-positive" },
                { label: "P75", value: s.p75AtRetirement, color: "text-terminal-text-primary" },
                { label: "Median (P50)", value: s.medianAtRetirement, color: "text-terminal-accent" },
                { label: "Mean", value: s.meanAtRetirement, color: "text-terminal-text-secondary" },
                { label: "P25", value: s.p25AtRetirement, color: "text-terminal-text-primary" },
                { label: "P5 (pessimistic)", value: s.p5AtRetirement, color: "text-terminal-negative" },
              ].map(({ label, value, color }) => (
                <div key={label} className="flex justify-between text-sm">
                  <span className="text-terminal-text-tertiary">{label}</span>
                  <Private>
                    <span className={`font-mono ${color}`}>
                      {formatLargeNumber(value)}
                    </span>
                  </Private>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-terminal-border">
              <div className="flex justify-between text-xs">
                <span className="text-terminal-text-tertiary">
                  Annual income at {formatPercent(withdrawalRate)} withdrawal
                </span>
                <Private>
                  <span className="font-mono text-terminal-text-primary">
                    {formatLargeNumber(Math.round(s.medianAtRetirement * (withdrawalRate / 100)))}
                  </span>
                </Private>
              </div>
            </div>
          </div>

          {/* Sensitivity Analysis */}
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
            <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">
              Sensitivity Analysis
            </h3>
            <div className="flex gap-1 mb-3 flex-wrap">
              {SENSITIVITY_VARIABLES.map((v) => (
                <button
                  key={v.key}
                  onClick={() => setSensVariable(v.key)}
                  className={`px-2 py-1 text-xs font-mono rounded transition-colors ${
                    sensVariable === v.key
                      ? "bg-terminal-accent/20 text-terminal-accent border border-terminal-accent/50"
                      : "text-terminal-text-secondary border border-terminal-border hover:text-terminal-text-primary"
                  }`}
                >
                  {v.label}
                </button>
              ))}
            </div>

            {sensLoading ? (
              <div className="h-[200px] flex items-center justify-center">
                <span className="text-sm text-terminal-text-tertiary animate-pulse">
                  Computing sensitivity...
                </span>
              </div>
            ) : sensData ? (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart
                  data={sensData.dataPoints}
                  margin={{ top: 5, right: 5, bottom: 0, left: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
                  <XAxis
                    dataKey="inputValue"
                    tick={{ fontSize: 10, fill: "#6B7280" }}
                    tickFormatter={(v) => fmtSensitivityInput(sensData.variable, v)}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#6B7280" }}
                    tickFormatter={(v) => fmtSensitivityOutput(sensData.outputMetric, v)}
                    width={55}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1F2937",
                      border: "1px solid #374151",
                      borderRadius: "4px",
                      fontSize: "11px",
                    }}
                    formatter={(val: number) => [
                      fmtSensitivityOutput(sensData.outputMetric, val),
                      "Median at Retirement",
                    ]}
                    labelFormatter={(val) =>
                      fmtSensitivityInput(sensData.variable, val)
                    }
                  />
                  {/* Baseline reference */}
                  <ReferenceLine
                    x={sensData.baseline.inputValue}
                    stroke="#F59E0B"
                    strokeDasharray="3 3"
                  />
                  <Line
                    type="monotone"
                    dataKey="outputValue"
                    stroke="#8B5CF6"
                    strokeWidth={2}
                    dot={{ fill: "#8B5CF6", r: 3 }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[200px] flex items-center justify-center">
                <span className="text-sm text-terminal-text-tertiary">
                  No sensitivity data
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Assumptions ── */}
      {p && (
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
          <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">
            Return Assumptions
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
            {[
              { label: "Equities", ret: p.expectedReturns.equities, color: "text-terminal-asset-stocks" },
              { label: "Fixed Income", ret: p.expectedReturns.fixedIncome, color: "text-terminal-asset-bonds" },
              { label: "Crypto", ret: p.expectedReturns.crypto, color: "text-terminal-asset-crypto" },
              { label: "Cash", ret: p.expectedReturns.cash, color: "text-terminal-asset-cash" },
            ].map(({ label, ret, color }) => (
              <div key={label} className="flex justify-between">
                <span className={color}>{label}</span>
                <span className="text-terminal-text-primary">{formatPercent(ret * 100)}</span>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-terminal-text-tertiary mt-2">
            Tax drag: 0.30% (accumulation), 0.50% (withdrawal) &bull; Inflation: 2.00% &bull; Crypto capped: [-90%, +500%] &bull; Correlations via Cholesky decomposition
          </p>
        </div>
      )}
    </div>
  );
}
