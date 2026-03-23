"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, apiGetRaw } from "@/lib/api";
import { TickerLink } from "@/components/ui/TickerLink";
import { formatCurrency, formatPercent } from "@/lib/format";
import { MetricCard } from "@/components/ui/MetricCard";
import { Private } from "@/lib/privacy";

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
        </div>
      )}
    </div>
  );
}
