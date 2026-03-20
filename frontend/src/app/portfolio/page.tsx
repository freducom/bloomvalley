"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { MetricCard } from "@/components/ui/MetricCard";

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
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"overview" | "holdings">("overview");

  useEffect(() => {
    const load = async () => {
      try {
        const [sum, hld] = await Promise.all([
          apiGet<PortfolioSummary>("/portfolio/summary"),
          apiGet<Holding[]>("/portfolio/holdings"),
        ]);
        setSummary(sum);
        setHoldings(hld);
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
        <div className="flex gap-1">
          {(["overview", "holdings"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 text-sm font-mono rounded ${
                tab === t
                  ? "bg-terminal-accent/20 text-terminal-accent"
                  : "text-terminal-text-secondary hover:text-terminal-text-primary"
              }`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Hero Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <MetricCard
          label="Total Value"
          value={isEmpty ? "\u20AC0.00" : formatCurrency(summary!.totalValueEurCents)}
          changeType="neutral"
        />
        <MetricCard
          label="Cost Basis"
          value={isEmpty ? "\u20AC0.00" : formatCurrency(summary!.totalCostEurCents)}
          changeType="neutral"
        />
        <MetricCard
          label="Unrealized P&L"
          value={
            isEmpty
              ? "\u20AC0.00"
              : formatCurrency(summary!.unrealizedPnlCents)
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
            isEmpty
              ? "\u20AC0.00"
              : formatCurrency(summary!.totalCashEurCents)
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
      ) : tab === "overview" ? (
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
                      {formatCurrency(cents)}
                    </div>
                    <div className="text-sm text-terminal-text-tertiary font-mono">
                      {pct}%
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
                    {formatCurrency(acct.valueCents)}
                  </div>
                  <div className="text-xs text-terminal-text-tertiary">
                    {acct.holdingsCount} holding
                    {acct.holdingsCount !== 1 ? "s" : ""}
                    {acct.cashBalanceCents > 0 && (
                      <span className="ml-2">
                        Cash: {formatCurrency(acct.cashBalanceCents, acct.cashCurrency)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        /* Holdings tab */
        <div className="border border-terminal-border rounded-md overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-terminal-bg-secondary text-terminal-text-secondary text-sm">
                <th className="text-left px-4 py-2 font-medium">Ticker</th>
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Account</th>
                <th className="text-left px-4 py-2 font-medium">Class</th>
                <th className="text-right px-4 py-2 font-medium">Qty</th>
                <th className="text-right px-4 py-2 font-medium">Avg Cost</th>
                <th className="text-right px-4 py-2 font-medium">Price</th>
                <th className="text-right px-4 py-2 font-medium">
                  Market Value
                </th>
                <th className="text-right px-4 py-2 font-medium">P&L</th>
                <th className="text-right px-4 py-2 font-medium">P&L %</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const pnlColor =
                  (h.unrealizedPnlCents ?? 0) > 0
                    ? "text-terminal-positive"
                    : (h.unrealizedPnlCents ?? 0) < 0
                    ? "text-terminal-negative"
                    : "text-terminal-text-tertiary";
                return (
                  <tr
                    key={`${h.accountId}-${h.securityId}`}
                    className="border-t border-terminal-border hover:bg-terminal-bg-secondary/50 transition-colors"
                  >
                    <td className="px-4 py-2 font-mono text-terminal-accent text-sm">
                      {h.ticker}
                    </td>
                    <td className="px-4 py-2 text-sm">{h.name}</td>
                    <td className="px-4 py-2 text-xs text-terminal-text-secondary">
                      {h.accountName}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`text-xs px-2 py-0.5 rounded font-mono ${
                          h.assetClass === "stock"
                            ? "bg-terminal-info/20 text-terminal-info"
                            : h.assetClass === "etf"
                            ? "bg-terminal-accent/20 text-terminal-accent"
                            : h.assetClass === "crypto"
                            ? "bg-terminal-warning/20 text-terminal-warning"
                            : "bg-terminal-bg-tertiary text-terminal-text-tertiary"
                        }`}
                      >
                        {h.assetClass}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {parseFloat(h.quantity).toLocaleString("en-US", {
                        maximumFractionDigits: 4,
                      })}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {formatCurrency(h.avgCostCents, h.currency)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {h.currentPriceCents != null ? (
                        <span>
                          {formatCurrency(
                            h.currentPriceCents,
                            h.priceCurrency
                          )}
                        </span>
                      ) : (
                        <span className="text-terminal-text-tertiary">--</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {h.marketValueEurCents != null
                        ? formatCurrency(h.marketValueEurCents)
                        : "--"}
                    </td>
                    <td
                      className={`px-4 py-2 text-right font-mono text-sm ${pnlColor}`}
                    >
                      {h.unrealizedPnlCents != null
                        ? formatCurrency(h.unrealizedPnlCents)
                        : "--"}
                    </td>
                    <td
                      className={`px-4 py-2 text-right font-mono text-sm ${pnlColor}`}
                    >
                      {h.unrealizedPnlPct != null
                        ? formatPercent(h.unrealizedPnlPct, true)
                        : "--"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
