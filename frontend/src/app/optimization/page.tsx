"use client";

import { useState, useEffect, useCallback } from "react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
  BarChart,
  Bar,
  Legend,
} from "recharts";
import { MetricCard } from "@/components/ui/MetricCard";
import { Private } from "@/lib/privacy";
import { formatCurrency, formatPercent } from "@/lib/format";
import { apiGetRaw } from "@/lib/api";
import { InfoTip } from "@/components/ui/InfoTip";

/* ── Types ── */

interface FrontierPoint {
  expectedReturn: number;
  volatility: number;
  sharpeRatio: number;
  weights: Record<string, number>;
}

interface FrontierData {
  frontier: FrontierPoint[];
  tangentPortfolio: FrontierPoint;
  minVariancePortfolio: FrontierPoint;
  assets: string[];
  tradingDays: number;
  riskFreeRate: number;
}

interface OptimalData {
  weights: Record<string, number>;
  expectedReturn: number;
  volatility: number;
  sharpeRatio: number;
  riskTolerance: number;
  glidepathCompliant: boolean;
  constraintViolations: string[];
}

interface RiskParityData {
  weights: Record<string, number>;
  riskContributions: Record<string, number>;
  portfolioVolatility: number;
  expectedReturn: number;
}

interface Trade {
  action: string;
  ticker: string;
  accountName: string;
  accountType: string;
  amountEurCents: number;
  estimatedTaxCents: number;
  rationale: string;
  priority: number;
}

interface RebalanceData {
  trades: Trade[];
  currentWeights: Record<string, number>;
  targetWeights: Record<string, number>;
  postTradeWeights: Record<string, number>;
  totalBuyCents: number;
  totalSellCents: number;
  totalEstimatedTaxCents: number;
  netCashRequiredCents: number;
  optimizationMethod: string;
}

type Tab = "frontier" | "optimal" | "riskParity" | "rebalance";

/* ── Page ── */

export default function OptimizationPage() {
  const [tab, setTab] = useState<Tab>("frontier");

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-terminal-text-primary">
          Portfolio Optimization
        </h1>
        <p className="text-sm text-terminal-text-secondary mt-1">
          Mean-variance optimization with glidepath constraints and tax-aware rebalancing
        </p>
      </div>

      <div className="flex gap-1 bg-terminal-bg-secondary rounded-lg p-1 border border-terminal-border w-fit">
        {([
          { key: "frontier" as Tab, label: "Efficient Frontier", tip: "The set of optimal portfolios that offer the highest expected return for each level of risk. Portfolios below the frontier are suboptimal — you can get more return for the same risk." },
          { key: "optimal" as Tab, label: "Optimal Portfolio", tip: "The portfolio allocation that maximizes the Sharpe ratio (risk-adjusted return) on the efficient frontier. Also called the tangent portfolio." },
          { key: "riskParity" as Tab, label: "Risk Parity", tip: "Allocation strategy where each asset contributes equally to total portfolio risk. Results in higher bond/low-vol allocations than market-cap weighting." },
          { key: "rebalance" as Tab, label: "Rebalance", tip: "Adjustments needed to bring current portfolio weights back to target allocations. Drift occurs naturally as assets move at different rates." },
        ]).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-1.5 text-sm rounded flex items-center gap-1 ${
              tab === t.key
                ? "bg-terminal-bg-tertiary text-terminal-text-primary"
                : "text-terminal-text-secondary hover:text-terminal-text-primary"
            }`}
          >
            {t.label}
            <InfoTip text={t.tip} />
          </button>
        ))}
      </div>

      {tab === "frontier" && <FrontierTab />}
      {tab === "optimal" && <OptimalTab />}
      {tab === "riskParity" && <RiskParityTab />}
      {tab === "rebalance" && <RebalanceTab />}
    </div>
  );
}

/* ── Efficient Frontier Tab ── */

function FrontierTab() {
  const [data, setData] = useState<FrontierData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    apiGetRaw<{ data: FrontierData | null; error?: string }>("/optimization/efficient-frontier")
      .then((res) => {
        if (res.error) setError(res.error);
        else setData(res.data);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Skeleton />;
  if (error) return <ErrorBox msg={error} />;
  if (!data) return <ErrorBox msg="No data available" />;

  const chartData = data.frontier.map((p) => ({
    x: p.volatility,
    y: p.expectedReturn,
    sharpe: p.sharpeRatio,
    type: "frontier",
  }));

  const tangent = {
    x: data.tangentPortfolio.volatility,
    y: data.tangentPortfolio.expectedReturn,
    sharpe: data.tangentPortfolio.sharpeRatio,
    type: "tangent",
  };

  const minVar = {
    x: data.minVariancePortfolio.volatility,
    y: data.minVariancePortfolio.expectedReturn,
    sharpe: data.minVariancePortfolio.sharpeRatio,
    type: "minVariance",
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Tangent Sharpe"
          value={data.tangentPortfolio.sharpeRatio.toFixed(3)}
          change={`Return: ${formatPercent(data.tangentPortfolio.expectedReturn)}`}
          changeType="positive"
        />
        <MetricCard
          label="Tangent Volatility"
          value={formatPercent(data.tangentPortfolio.volatility)}
          changeType="neutral"
        />
        <MetricCard
          label="Min Variance Vol"
          value={formatPercent(data.minVariancePortfolio.volatility)}
          change={`Return: ${formatPercent(data.minVariancePortfolio.expectedReturn)}`}
          changeType="neutral"
        />
        <MetricCard
          label="Trading Days"
          value={data.tradingDays.toString()}
          change={`${data.frontier.length} frontier points`}
          changeType="neutral"
        />
      </div>

      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <h3 className="text-sm font-medium text-terminal-text-secondary mb-4 flex items-center gap-1">
          Efficient Frontier
          <InfoTip text="The set of optimal portfolios that offer the highest expected return for each level of risk. Portfolios below the frontier are suboptimal — you can get more return for the same risk." />
        </h3>
        <ResponsiveContainer width="100%" height={400}>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
            <XAxis
              dataKey="x"
              type="number"
              name="Volatility"
              unit="%"
              tick={{ fontSize: 11, fill: "#6B7280" }}
              label={{ value: "Volatility (%)", position: "insideBottom", offset: -5, fontSize: 11, fill: "#6B7280" }}
            />
            <YAxis
              dataKey="y"
              type="number"
              name="Return"
              unit="%"
              tick={{ fontSize: 11, fill: "#6B7280" }}
              label={{ value: "Expected Return (%)", angle: -90, position: "insideLeft", fontSize: 11, fill: "#6B7280" }}
            />
            <Tooltip
              contentStyle={{ backgroundColor: "#1F2937", border: "1px solid #374151", borderRadius: "4px", fontSize: "11px" }}
              formatter={(val: number, name: string) => [`${val.toFixed(2)}%`, name === "x" ? "Volatility" : "Return"]}
            />
            <Scatter data={chartData} fill="#8B5CF6" fillOpacity={0.6} r={4} />
            <Scatter data={[tangent]} fill="#22C55E" r={8} name="Tangent" />
            <Scatter data={[minVar]} fill="#3B82F6" r={8} name="Min Variance" />
          </ScatterChart>
        </ResponsiveContainer>
        <div className="flex items-center justify-center gap-6 mt-3 text-xs text-terminal-text-tertiary">
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#8B5CF6]" /> Frontier</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#22C55E]" /> Tangent (Max Sharpe)</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#3B82F6]" /> Min Variance</span>
        </div>
      </div>

      <WeightsTable label="Tangent Portfolio Weights" weights={data.tangentPortfolio.weights} />
    </div>
  );
}

/* ── Optimal Portfolio Tab ── */

function OptimalTab() {
  const [riskTolerance, setRiskTolerance] = useState(5);
  const [data, setData] = useState<OptimalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGetRaw<{ data: OptimalData | null; error?: string }>(
        `/optimization/optimal?riskTolerance=${riskTolerance}`
      );
      if (res.error) setError(res.error);
      else setData(res.data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [riskTolerance]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <h3 className="text-sm font-medium text-terminal-text-secondary mb-3 flex items-center gap-1">
          Optimal Portfolio
          <InfoTip text="The portfolio allocation that maximizes the Sharpe ratio (risk-adjusted return) on the efficient frontier. Also called the tangent portfolio." />
        </h3>
        <div className="flex items-center gap-4">
          <span className="text-xs text-terminal-text-tertiary">Aggressive</span>
          <input
            type="range"
            min={1}
            max={10}
            value={riskTolerance}
            onChange={(e) => setRiskTolerance(Number(e.target.value))}
            className="flex-1 accent-terminal-accent"
          />
          <span className="text-xs text-terminal-text-tertiary">Conservative</span>
          <span className="font-mono text-sm text-terminal-accent w-8 text-center">{riskTolerance}</span>
        </div>
      </div>

      {loading && <Skeleton />}
      {error && <ErrorBox msg={error} />}

      {data && !loading && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Expected Return"
              value={formatPercent(data.expectedReturn)}
              changeType="positive"
            />
            <MetricCard
              label="Volatility"
              value={formatPercent(data.volatility)}
              changeType="neutral"
            />
            <MetricCard
              label="Sharpe Ratio"
              value={data.sharpeRatio.toFixed(3)}
              changeType={data.sharpeRatio >= 1 ? "positive" : "neutral"}
            />
            <MetricCard
              label="Glidepath"
              value={data.glidepathCompliant ? "Compliant" : "Violation"}
              changeType={data.glidepathCompliant ? "positive" : "negative"}
            />
          </div>

          {data.constraintViolations?.length > 0 && (
            <div className="text-sm text-terminal-warning bg-terminal-warning/10 border border-terminal-warning/20 rounded p-3">
              {data.constraintViolations.map((v, i) => <div key={i}>{v}</div>)}
            </div>
          )}

          <WeightsTable label="Optimal Weights" weights={data.weights} />
        </>
      )}
    </div>
  );
}

/* ── Risk Parity Tab ── */

function RiskParityTab() {
  const [data, setData] = useState<RiskParityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    apiGetRaw<{ data: RiskParityData | null; error?: string }>("/optimization/risk-parity")
      .then((res) => {
        if (res.error) setError(res.error);
        else setData(res.data);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Skeleton />;
  if (error) return <ErrorBox msg={error} />;
  if (!data) return <ErrorBox msg="No data available" />;

  const chartData = Object.entries(data.weights)
    .filter(([, w]) => w >= 0.001)
    .map(([ticker, w]) => ({
      ticker,
      weight: +(w * 100).toFixed(2),
      riskContribution: +((data.riskContributions[ticker] || 0) * 100).toFixed(2),
    }))
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 15);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Expected Return"
          value={formatPercent(data.expectedReturn * 100)}
          changeType="positive"
        />
        <MetricCard
          label="Portfolio Volatility"
          value={formatPercent(data.portfolioVolatility * 100)}
          changeType="neutral"
        />
        <MetricCard
          label="Holdings"
          value={Object.keys(data.weights).filter((k) => data.weights[k] >= 0.001).length.toString()}
          changeType="neutral"
        />
        <MetricCard
          label="Method"
          value="Equal Risk"
          change="Each asset contributes equal risk"
          changeType="neutral"
        />
      </div>

      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <h3 className="text-sm font-medium text-terminal-text-secondary mb-4 flex items-center gap-1">
          Risk Parity — Weights vs Risk Contribution (top 15)
          <InfoTip text="Allocation strategy where each asset contributes equally to total portfolio risk. Results in higher bond/low-vol allocations than market-cap weighting." />
        </h3>
        <ResponsiveContainer width="100%" height={350}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 20, bottom: 5, left: 60 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
            <XAxis type="number" tick={{ fontSize: 10, fill: "#6B7280" }} unit="%" />
            <YAxis dataKey="ticker" type="category" tick={{ fontSize: 10, fill: "#6B7280" }} width={55} />
            <Tooltip
              contentStyle={{ backgroundColor: "#1F2937", border: "1px solid #374151", borderRadius: "4px", fontSize: "11px" }}
            />
            <Bar dataKey="weight" fill="#8B5CF6" name="Weight %" barSize={10} />
            <Bar dataKey="riskContribution" fill="#F59E0B" name="Risk Contrib %" barSize={10} />
            <Legend wrapperStyle={{ fontSize: "11px" }} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ── Rebalance Tab ── */

function RebalanceTab() {
  const [riskTolerance, setRiskTolerance] = useState(5);
  const [data, setData] = useState<RebalanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGetRaw<{ data: RebalanceData | null; error?: string }>(
        `/optimization/rebalance?riskTolerance=${riskTolerance}`
      );
      if (res.error) setError(res.error);
      else setData(res.data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [riskTolerance]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <h3 className="text-sm font-medium text-terminal-text-secondary mb-3 flex items-center gap-1">
          Rebalance
          <InfoTip text="Adjustments needed to bring current portfolio weights back to target allocations. Drift occurs naturally as assets move at different rates." />
        </h3>
        <div className="flex items-center gap-4">
          <span className="text-xs text-terminal-text-tertiary">Aggressive</span>
          <input type="range" min={1} max={10} value={riskTolerance}
            onChange={(e) => setRiskTolerance(Number(e.target.value))}
            className="flex-1 accent-terminal-accent"
          />
          <span className="text-xs text-terminal-text-tertiary">Conservative</span>
          <span className="font-mono text-sm text-terminal-accent w-8 text-center">{riskTolerance}</span>
        </div>
      </div>

      {loading && <Skeleton />}
      {error && <ErrorBox msg={error} />}

      {data && !loading && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Total Buys"
              value={<Private>{formatCurrency(data.totalBuyCents)}</Private>}
              changeType="positive"
            />
            <MetricCard
              label="Total Sells"
              value={<Private>{formatCurrency(data.totalSellCents)}</Private>}
              changeType="negative"
            />
            <MetricCard
              label="Estimated Tax"
              value={<Private>{formatCurrency(data.totalEstimatedTaxCents)}</Private>}
              changeType="negative"
            />
            <MetricCard
              label="Net Cash Required"
              value={<Private>{formatCurrency(data.netCashRequiredCents)}</Private>}
              changeType="neutral"
            />
          </div>

          {data.trades.length === 0 ? (
            <div className="text-center py-12 text-terminal-text-secondary">
              No rebalancing trades needed — portfolio is within target allocation.
            </div>
          ) : (
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-terminal-bg-tertiary text-terminal-text-secondary text-left">
                    <th className="px-3 py-2 font-medium">#</th>
                    <th className="px-3 py-2 font-medium">Action</th>
                    <th className="px-3 py-2 font-medium">Ticker</th>
                    <th className="px-3 py-2 font-medium">Account</th>
                    <th className="px-3 py-2 font-medium text-right">Amount</th>
                    <th className="px-3 py-2 font-medium text-right">Tax</th>
                    <th className="px-3 py-2 font-medium">Rationale</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-terminal-border">
                  {data.trades.map((t, i) => (
                    <tr key={i} className="hover:bg-terminal-bg-secondary/50">
                      <td className="px-3 py-2 text-terminal-text-tertiary">{t.priority}</td>
                      <td className="px-3 py-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          t.action === "buy"
                            ? "bg-terminal-positive/20 text-terminal-positive"
                            : "bg-terminal-negative/20 text-terminal-negative"
                        }`}>
                          {t.action.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono font-medium">{t.ticker}</td>
                      <td className="px-3 py-2 text-terminal-text-secondary text-xs">{t.accountName}</td>
                      <td className="px-3 py-2 text-right font-mono">
                        <Private>{formatCurrency(t.amountEurCents)}</Private>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-terminal-text-tertiary">
                        <Private>{t.estimatedTaxCents > 0 ? formatCurrency(t.estimatedTaxCents) : "—"}</Private>
                      </td>
                      <td className="px-3 py-2 text-xs text-terminal-text-secondary max-w-[300px] truncate">
                        {t.rationale}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── Shared Components ── */

function WeightsTable({ label, weights }: { label: string; weights: Record<string, number> }) {
  const sorted = Object.entries(weights)
    .filter(([, w]) => w >= 0.001)
    .sort((a, b) => b[1] - a[1]);

  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
      <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">{label}</h3>
      <div className="space-y-1.5">
        {sorted.map(([ticker, w]) => (
          <div key={ticker} className="flex items-center gap-3">
            <span className="font-mono text-xs w-16 text-terminal-text-primary">{ticker}</span>
            <div className="flex-1 h-4 bg-terminal-bg-primary rounded-sm overflow-hidden">
              <div
                className="h-full bg-terminal-accent/60 rounded-sm"
                style={{ width: `${w * 100}%` }}
              />
            </div>
            <span className="font-mono text-xs w-14 text-right text-terminal-text-secondary">
              {formatPercent(w * 100)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-[88px] bg-terminal-bg-secondary rounded-md" />
        ))}
      </div>
      <div className="h-[400px] bg-terminal-bg-secondary rounded-md" />
    </div>
  );
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="text-sm text-terminal-warning bg-terminal-warning/10 border border-terminal-warning/20 rounded p-3">
      {msg}
    </div>
  );
}
