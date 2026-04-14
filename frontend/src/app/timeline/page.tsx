"use client";

import { useEffect, useState } from "react";
import { apiGet, apiGetRaw } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { MetricCard } from "@/components/ui/MetricCard";
import { Private } from "@/lib/privacy";
import { InfoTip } from "@/components/ui/InfoTip";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, Cell,
} from "recharts";

/* ── Types ── */

interface CandidateTicker {
  ticker: string;
  name?: string;
  rationale?: string;
  allocationPct?: number;
}

interface ConditionalTrigger {
  condition: string;
  threshold?: number;
  action: string;
}

interface Tranche {
  id: number;
  planId: number;
  quarterLabel: string;
  plannedDate: string;
  amountCents: number;
  currency: string;
  coreAllocationPct: number;
  convictionAllocationPct: number;
  cashBufferPct: number;
  candidateTickers: CandidateTicker[] | null;
  conditionalTriggers: ConditionalTrigger[] | null;
  status: string;
  executedDate: string | null;
  executedAmountCents: number | null;
  executionNotes: string | null;
}

interface DeploymentPlan {
  id: number;
  name: string;
  status: string;
  startDate: string;
  endDate: string;
  totalAmountCents: number;
  deployedAmountCents: number;
  currency: string;
  strategyNotes: string | null;
  macroRegimeAtCreation: string | null;
  nextReviewDate: string | null;
  tranches: Tranche[];
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

/* ── Status Colors ── */

const STATUS_COLORS: Record<string, { bg: string; text: string; bar: string }> = {
  planned: { bg: "bg-gray-500/10", text: "text-gray-400", bar: "#6b7280" },
  active: { bg: "bg-blue-500/10", text: "text-blue-400", bar: "#3b82f6" },
  completed: { bg: "bg-emerald-500/10", text: "text-emerald-400", bar: "#22c55e" },
  accelerated: { bg: "bg-amber-500/10", text: "text-amber-400", bar: "#f59e0b" },
  deferred: { bg: "bg-red-500/10", text: "text-red-400", bar: "#ef4444" },
};

/* ── Page ── */

export default function TimelinePage() {
  const [plan, setPlan] = useState<DeploymentPlan | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiGetRaw<{ data: DeploymentPlan | null }>("/deployment-plans/current"),
      apiGet<Recommendation[]>("/recommendations?status=active&limit=50"),
    ])
      .then(([planRes, recsData]) => {
        setPlan(planRes.data);
        setRecs(recsData || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Capital Deployment Timeline <InfoTip text="Quarterly capital deployment schedule. Defines how much new capital to invest each quarter, split between core index holdings and high-conviction satellite positions." /></h1>
        <div className="h-64 bg-terminal-bg-secondary rounded animate-pulse" />
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Capital Deployment Timeline <InfoTip text="Quarterly capital deployment schedule. Defines how much new capital to invest each quarter, split between core index holdings and high-conviction satellite positions." /></h1>
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-8 text-center">
          <p className="text-terminal-text-secondary mb-4">
            No active deployment plan. The portfolio manager will create one on the next analyst swarm run.
          </p>
          <p className="text-terminal-text-secondary text-sm">
            The plan provides a stable 12-month strategic framework for capital allocation —
            quarterly tranches with target dates, amounts, and candidate securities.
          </p>
        </div>
      </div>
    );
  }

  const deployed = plan.deployedAmountCents;
  const remaining = plan.totalAmountCents - deployed;
  const nextTranche = plan.tranches.find(
    (t) => t.status === "planned" || t.status === "active"
  );
  const reviewDue = plan.nextReviewDate && plan.nextReviewDate <= new Date().toISOString().slice(0, 10);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Capital Deployment Timeline <InfoTip text="Quarterly capital deployment schedule. Defines how much new capital to invest each quarter, split between core index holdings and high-conviction satellite positions." /></h1>
          <p className="text-terminal-text-secondary text-sm mt-1">{plan.name}</p>
        </div>
        {reviewDue && (
          <span className="px-3 py-1 text-xs font-semibold rounded bg-amber-500/20 text-amber-400 border border-amber-500/30">
            Review Due
          </span>
        )}
      </div>

      {/* Metric Cards */}
      <Private>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard
            label="Total Plan"
            value={formatCurrency(plan.totalAmountCents)}
          />
          <MetricCard
            label="Deployed"
            value={formatCurrency(deployed)}
            subValue={`${((deployed / plan.totalAmountCents) * 100).toFixed(0)}%`}
          />
          <MetricCard
            label="Remaining"
            value={formatCurrency(remaining)}
          />
          <MetricCard
            label="Next Tranche"
            value={nextTranche ? nextTranche.quarterLabel : "—"}
            subValue={nextTranche ? formatCurrency(nextTranche.amountCents) : undefined}
          />
        </div>
      </Private>

      {/* Strategy Notes */}
      {plan.strategyNotes && (
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
          <h3 className="text-sm font-semibold text-terminal-text-secondary mb-1">Strategy</h3>
          <p className="text-sm text-terminal-text-primary">{plan.strategyNotes}</p>
        </div>
      )}

      {/* Visual Timeline Chart */}
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <h3 className="text-sm font-semibold text-terminal-text-secondary mb-3">Deployment Schedule</h3>
        <Private>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={plan.tranches.map((t) => ({
                name: t.quarterLabel,
                amount: t.amountCents / 100,
                executed: (t.executedAmountCents || 0) / 100,
                status: t.status,
                date: t.plannedDate,
              }))}
              margin={{ top: 5, right: 5, bottom: 5, left: 5 }}
            >
              <XAxis
                dataKey="name"
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "#6b7280" }}
                tickFormatter={(v: number) =>
                  v >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v}`
                }
                axisLine={false}
                tickLine={false}
                width={45}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1a1f2e",
                  border: "1px solid #2d3548",
                  borderRadius: "4px",
                  fontSize: "12px",
                  color: "#e5e7eb",
                }}
                labelStyle={{ color: "#9ca3af" }}
                itemStyle={{ color: "#e5e7eb" }}
                cursor={{ fill: "rgba(139, 92, 246, 0.1)" }}
                formatter={(value: number, name: string) => [
                  `€${value.toLocaleString()}`,
                  name === "executed" ? "Executed" : "Planned",
                ]}
              />
              <Bar dataKey="amount" radius={[4, 4, 0, 0]}>
                {plan.tranches.map((t, i) => (
                  <Cell
                    key={i}
                    fill={STATUS_COLORS[t.status]?.bar || "#6b7280"}
                    fillOpacity={t.status === "completed" ? 0.3 : 0.8}
                  />
                ))}
              </Bar>
              {plan.tranches.some((t) => t.executedAmountCents) && (
                <Bar dataKey="executed" fill="#22c55e" radius={[4, 4, 0, 0]} />
              )}
            </BarChart>
          </ResponsiveContainer>
        </Private>
        <div className="flex gap-4 mt-2 text-xs text-terminal-text-secondary">
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-sm bg-gray-500/80 inline-block" /> Planned
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-sm bg-blue-500/80 inline-block" /> Active
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-sm bg-emerald-500/80 inline-block" /> Completed
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-sm bg-amber-500/80 inline-block" /> Accelerated
          </span>
        </div>
      </div>

      {/* Tranche Detail Cards */}
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-terminal-text-secondary">Tranches <InfoTip text="A scheduled batch of capital to deploy. Each tranche specifies the amount, target allocation (core vs conviction), and deployment quarter." /></h3>
        {plan.tranches.map((tranche) => (
          <TrancheCard key={tranche.id} tranche={tranche} recs={recs} />
        ))}
      </div>
    </div>
  );
}

/* ── Tranche Card ── */

function TrancheCard({ tranche, recs }: { tranche: Tranche; recs: Recommendation[] }) {
  const colors = STATUS_COLORS[tranche.status] || STATUS_COLORS.planned;
  const isNext =
    tranche.status === "planned" || tranche.status === "active";
  const imminentDays = isNext
    ? Math.ceil(
        (new Date(tranche.plannedDate).getTime() - Date.now()) / 86400000
      )
    : null;
  const isImminent = imminentDays !== null && imminentDays <= 14 && imminentDays >= 0;

  // Match recommendations to candidate tickers
  const candidateTickers = (tranche.candidateTickers || []).map(
    (c) => c.ticker
  );
  const matchedRecs = recs.filter((r) => candidateTickers.includes(r.ticker));

  return (
    <div
      className={`border rounded-md p-4 ${
        isImminent
          ? "border-blue-500/50 bg-blue-500/5"
          : "border-terminal-border bg-terminal-bg-secondary"
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h4 className="text-base font-semibold">{tranche.quarterLabel}</h4>
          <span className="text-sm text-terminal-text-secondary">
            {new Date(tranche.plannedDate).toLocaleDateString("en-GB", {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </span>
          {isImminent && (
            <span className="px-2 py-0.5 text-xs font-semibold rounded bg-blue-500/20 text-blue-400">
              {imminentDays === 0 ? "Today" : `${imminentDays}d away`}
            </span>
          )}
        </div>
        <span
          className={`px-2 py-0.5 text-xs font-semibold rounded ${colors.bg} ${colors.text}`}
        >
          {tranche.status.toUpperCase()}
        </span>
      </div>

      {/* Amount + Deployment Progress + Allocation */}
      <Private>
        <div className="flex items-center gap-4 mb-3">
          <div>
            <span className="text-lg font-bold">
              {formatCurrency(tranche.amountCents)}
            </span>
            {(tranche.executedAmountCents ?? 0) > 0 && (
              <div className="text-xs text-terminal-text-secondary mt-0.5">
                <span className="text-emerald-400 font-semibold">
                  {formatCurrency(tranche.executedAmountCents ?? 0)}
                </span>
                {" deployed "}
                <span className="text-terminal-text-tertiary">
                  ({Math.round(((tranche.executedAmountCents ?? 0) / tranche.amountCents) * 100)}%)
                </span>
                {tranche.amountCents > (tranche.executedAmountCents ?? 0) && (
                  <span className="text-terminal-text-tertiary">
                    {" — "}{formatCurrency(tranche.amountCents - (tranche.executedAmountCents ?? 0))} remaining
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="flex-1">
            {/* Deployment progress bar */}
            {(tranche.executedAmountCents ?? 0) > 0 && (
              <div className="flex h-1.5 rounded-full overflow-hidden bg-terminal-bg-primary mb-1.5">
                <div
                  className="bg-emerald-500 transition-all"
                  style={{ width: `${Math.min(100, ((tranche.executedAmountCents ?? 0) / tranche.amountCents) * 100)}%` }}
                />
              </div>
            )}
            {/* Allocation split bar */}
            <div className="flex h-2 rounded-full overflow-hidden bg-terminal-bg-primary">
              <div
                className="bg-blue-500"
                style={{ width: `${tranche.coreAllocationPct}%` }}
                title={`Core: ${tranche.coreAllocationPct}%`}
              />
              <div
                className="bg-purple-500"
                style={{ width: `${tranche.convictionAllocationPct}%` }}
                title={`Conviction: ${tranche.convictionAllocationPct}%`}
              />
              <div
                className="bg-gray-500"
                style={{ width: `${tranche.cashBufferPct}%` }}
                title={`Cash buffer: ${tranche.cashBufferPct}%`}
              />
            </div>
            <div className="flex text-xs text-terminal-text-secondary mt-1 gap-3">
              <span>Core {tranche.coreAllocationPct}% <InfoTip text="Index fund allocation (60-70% of portfolio). Low-cost, broad market exposure following the Boglehead philosophy." /></span>
              <span>Conviction {tranche.convictionAllocationPct}% <InfoTip text="Individual stock picks (30-40% of portfolio). High-conviction Munger-style positions with demonstrated competitive advantages." /></span>
              <span>Cash {tranche.cashBufferPct}% <InfoTip text="Cash reserve maintained for opportunistic purchases during market downturns. Typically 3-5% of portfolio value." /></span>
            </div>
          </div>
        </div>
      </Private>

      {/* Execution notes */}
      {tranche.executionNotes && (
        <div className="text-xs text-terminal-text-tertiary bg-terminal-bg-primary rounded px-3 py-1.5 mb-3 font-mono">
          {tranche.executionNotes}
        </div>
      )}

      {/* Candidate Securities */}
      {tranche.candidateTickers && tranche.candidateTickers.length > 0 && (
        <div className="mb-3">
          <h5 className="text-xs font-semibold text-terminal-text-secondary mb-1">
            Candidate Securities
          </h5>
          <div className="flex flex-wrap gap-2">
            {tranche.candidateTickers.map((c, i) => (
              <span
                key={i}
                className="px-2 py-1 text-xs rounded bg-terminal-bg-primary border border-terminal-border"
                title={c.rationale || ""}
              >
                <span className="font-semibold text-terminal-accent">
                  {c.ticker}
                </span>
                {c.allocationPct && (
                  <span className="text-terminal-text-secondary ml-1">
                    {c.allocationPct}%
                  </span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Conditional Triggers */}
      {tranche.conditionalTriggers && tranche.conditionalTriggers.length > 0 && (
        <div className="mb-3">
          <h5 className="text-xs font-semibold text-terminal-text-secondary mb-1">
            Conditional Triggers
          </h5>
          {tranche.conditionalTriggers.map((tr, i) => (
            <div
              key={i}
              className="text-xs text-amber-400 bg-amber-500/10 rounded px-2 py-1 mb-1"
            >
              If {tr.condition}
              {tr.threshold !== undefined && ` (${tr.threshold})`} → {tr.action}
            </div>
          ))}
        </div>
      )}

      {/* Active Recommendations for this tranche */}
      {matchedRecs.length > 0 && (
        <div className="mb-3">
          <h5 className="text-xs font-semibold text-terminal-text-secondary mb-1">
            Active Recommendations
          </h5>
          {matchedRecs.map((r) => {
            const daysSince = Math.ceil(
              (Date.now() - new Date(r.recommendedDate).getTime()) / 86400000
            );
            const actionColor =
              r.action === "buy" || r.action === "BUY"
                ? "text-emerald-400"
                : r.action === "sell" || r.action === "SELL"
                ? "text-red-400"
                : "text-gray-400";
            return (
              <div
                key={r.id}
                className="text-xs flex items-center gap-2 mb-1"
              >
                <span className={`font-semibold ${actionColor}`}>
                  {r.action.toUpperCase()}
                </span>
                <span className="text-terminal-text-primary font-mono">
                  {r.ticker}
                </span>
                <span className="text-terminal-text-secondary">
                  {daysSince}d ago
                </span>
                {daysSince <= 10 && (
                  <span className="text-xs text-blue-400">
                    (stability window)
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Execution info for completed tranches */}
      {tranche.status === "completed" && tranche.executedDate && (
        <Private>
          <div className="text-xs text-emerald-400 bg-emerald-500/10 rounded px-2 py-1">
            Executed {tranche.executedDate}:{" "}
            {formatCurrency(tranche.executedAmountCents || 0)}
            {tranche.executionNotes && ` — ${tranche.executionNotes}`}
          </div>
        </Private>
      )}
    </div>
  );
}
