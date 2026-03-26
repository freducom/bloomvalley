"use client";

import { useState, useEffect } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from "recharts";
import { MetricCard } from "@/components/ui/MetricCard";
import { Private } from "@/lib/privacy";
import { formatCurrency, formatPercent, formatLargeNumber } from "@/lib/format";
import { apiGetRaw } from "@/lib/api";

/* ── Types ── */

interface Exposure {
  currency: string;
  valueCents: number;
  weightPct: number;
  holdingsCount: number;
}

interface FxRateInfo {
  currency: string;
  rate: number;
  change1D: number | null;
  change1W: number | null;
  change1M: number | null;
  change3M: number | null;
}

interface FxImpactCurrency {
  currency: string;
  exposureCents: number;
  impact1DCents: number | null;
  impact1WCents: number | null;
  impact1MCents: number | null;
  impact3MCents: number | null;
}

interface FxImpact {
  total1DCents: number | null;
  total1DPct: number | null;
  total1WCents: number | null;
  total1WPct: number | null;
  total1MCents: number | null;
  total1MPct: number | null;
  total3MCents: number | null;
  total3MPct: number | null;
  byCurrency: FxImpactCurrency[];
}

interface HoldingDetail {
  ticker: string;
  name: string;
  currency: string;
  marketValueEurCents: number;
  fxRate: number;
}

interface CurrencyExposureData {
  exposures: Exposure[];
  fxRates: FxRateInfo[];
  fxImpact: FxImpact;
  holdings: HoldingDetail[];
}

/* ── Currency Colors ── */

const CURRENCY_COLORS: Record<string, string> = {
  EUR: "#8B5CF6",
  USD: "#3B82F6",
  SEK: "#22C55E",
  GBP: "#F59E0B",
  NOK: "#EF4444",
  DKK: "#06B6D4",
  CHF: "#EC4899",
  JPY: "#F97316",
};

function getCurrencyColor(currency: string): string {
  return CURRENCY_COLORS[currency] || "#6B7280";
}

/* ── Page ── */

export default function HedgingPage() {
  const [data, setData] = useState<CurrencyExposureData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    apiGetRaw<{ data: CurrencyExposureData }>("/portfolio/currency-exposure")
      .then((res) => setData(res.data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <h1 className="text-2xl font-bold text-terminal-text-primary mb-6">Currency Exposure</h1>
        <div className="animate-pulse space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-[88px] bg-terminal-bg-secondary rounded-md" />
            ))}
          </div>
          <div className="h-[300px] bg-terminal-bg-secondary rounded-md" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <h1 className="text-2xl font-bold text-terminal-text-primary mb-6">Currency Exposure</h1>
        <div className="text-sm text-terminal-warning bg-terminal-warning/10 border border-terminal-warning/20 rounded p-3">
          {error}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const nonEurPct = data.exposures
    .filter((e) => e.currency !== "EUR")
    .reduce((s, e) => s + e.weightPct, 0);

  const imp = data.fxImpact;

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-terminal-text-primary">Currency Exposure</h1>
        <p className="text-sm text-terminal-text-secondary mt-1">
          FX risk analysis — how currency movements affect your portfolio
        </p>
      </div>

      {/* Summary Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Non-EUR Exposure"
          value={formatPercent(nonEurPct)}
          change={`${data.exposures.filter((e) => e.currency !== "EUR").length} currencies`}
          changeType={nonEurPct > 50 ? "negative" : "neutral"}
        />
        <MetricCard
          label="FX Impact (1W)"
          value={imp.total1WPct != null ? formatPercent(imp.total1WPct, true) : "—"}
          change={imp.total1WCents != null ? formatCurrency(imp.total1WCents) : ""}
          changeType={
            imp.total1WPct == null ? "neutral" : imp.total1WPct >= 0 ? "positive" : "negative"
          }
        />
        <MetricCard
          label="FX Impact (1M)"
          value={imp.total1MPct != null ? formatPercent(imp.total1MPct, true) : "—"}
          change={imp.total1MCents != null ? formatCurrency(imp.total1MCents) : ""}
          changeType={
            imp.total1MPct == null ? "neutral" : imp.total1MPct >= 0 ? "positive" : "negative"
          }
        />
        <MetricCard
          label="FX Impact (3M)"
          value={imp.total3MPct != null ? formatPercent(imp.total3MPct, true) : "—"}
          change={imp.total3MCents != null ? formatCurrency(imp.total3MCents) : ""}
          changeType={
            imp.total3MPct == null ? "neutral" : imp.total3MPct >= 0 ? "positive" : "negative"
          }
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Currency Exposure Bar Chart */}
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
          <h3 className="text-sm font-medium text-terminal-text-secondary mb-4">
            Allocation by Currency
          </h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart
              data={data.exposures}
              layout="vertical"
              margin={{ top: 5, right: 20, bottom: 5, left: 40 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
              <XAxis type="number" tick={{ fontSize: 10, fill: "#6B7280" }} unit="%" />
              <YAxis dataKey="currency" type="category" tick={{ fontSize: 11, fill: "#6B7280" }} width={35} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1F2937", border: "1px solid #374151", borderRadius: "4px", fontSize: "11px" }}
                formatter={(val: number) => [formatPercent(val), "Weight"]}
              />
              <Bar dataKey="weightPct" barSize={16}>
                {data.exposures.map((e, i) => (
                  <Cell key={i} fill={getCurrencyColor(e.currency)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* FX Rate Changes Table */}
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
          <h3 className="text-sm font-medium text-terminal-text-secondary mb-4">
            EUR Exchange Rates
          </h3>
          {data.fxRates.length === 0 ? (
            <div className="text-center py-8 text-terminal-text-secondary text-sm">
              All holdings are EUR-denominated
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-terminal-text-tertiary text-left text-xs">
                  <th className="pb-2 font-medium">Currency</th>
                  <th className="pb-2 font-medium text-right">Rate</th>
                  <th className="pb-2 font-medium text-right">1D</th>
                  <th className="pb-2 font-medium text-right">1W</th>
                  <th className="pb-2 font-medium text-right">1M</th>
                  <th className="pb-2 font-medium text-right">3M</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-terminal-border">
                {data.fxRates.map((fx) => (
                  <tr key={fx.currency}>
                    <td className="py-2 font-mono font-medium">
                      <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ backgroundColor: getCurrencyColor(fx.currency) }} />
                      EUR/{fx.currency}
                    </td>
                    <td className="py-2 text-right font-mono">{fx.rate.toFixed(4)}</td>
                    <td className="py-2 text-right font-mono">
                      <FxChange value={fx.change1D} />
                    </td>
                    <td className="py-2 text-right font-mono">
                      <FxChange value={fx.change1W} />
                    </td>
                    <td className="py-2 text-right font-mono">
                      <FxChange value={fx.change1M} />
                    </td>
                    <td className="py-2 text-right font-mono">
                      <FxChange value={fx.change3M} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* FX Impact by Currency */}
      {data.fxImpact.byCurrency.length > 0 && (
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
          <h3 className="text-sm font-medium text-terminal-text-secondary mb-4">
            FX Impact by Currency
          </h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-terminal-text-tertiary text-left text-xs">
                <th className="pb-2 font-medium">Currency</th>
                <th className="pb-2 font-medium text-right">Exposure</th>
                <th className="pb-2 font-medium text-right">1D Impact</th>
                <th className="pb-2 font-medium text-right">1W Impact</th>
                <th className="pb-2 font-medium text-right">1M Impact</th>
                <th className="pb-2 font-medium text-right">3M Impact</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border">
              {data.fxImpact.byCurrency.map((c) => (
                <tr key={c.currency}>
                  <td className="py-2 font-mono font-medium">{c.currency}</td>
                  <td className="py-2 text-right font-mono">
                    <Private>{formatLargeNumber(c.exposureCents)}</Private>
                  </td>
                  <td className="py-2 text-right font-mono">
                    <ImpactCell cents={c.impact1DCents} />
                  </td>
                  <td className="py-2 text-right font-mono">
                    <ImpactCell cents={c.impact1WCents} />
                  </td>
                  <td className="py-2 text-right font-mono">
                    <ImpactCell cents={c.impact1MCents} />
                  </td>
                  <td className="py-2 text-right font-mono">
                    <ImpactCell cents={c.impact3MCents} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Per-holding Breakdown */}
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <h3 className="text-sm font-medium text-terminal-text-secondary mb-4">
          Holdings by Currency
        </h3>
        <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-terminal-bg-secondary">
              <tr className="text-terminal-text-tertiary text-left text-xs">
                <th className="pb-2 font-medium">Ticker</th>
                <th className="pb-2 font-medium">Name</th>
                <th className="pb-2 font-medium">Currency</th>
                <th className="pb-2 font-medium text-right">FX Rate</th>
                <th className="pb-2 font-medium text-right">Value (EUR)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border">
              {data.holdings
                .sort((a, b) => b.marketValueEurCents - a.marketValueEurCents)
                .map((h, i) => (
                  <tr key={i} className="hover:bg-terminal-bg-tertiary/50">
                    <td className="py-1.5 font-mono font-medium">{h.ticker}</td>
                    <td className="py-1.5 text-terminal-text-secondary truncate max-w-[200px]">{h.name}</td>
                    <td className="py-1.5">
                      <span
                        className="inline-block w-2 h-2 rounded-full mr-1.5"
                        style={{ backgroundColor: getCurrencyColor(h.currency) }}
                      />
                      {h.currency}
                    </td>
                    <td className="py-1.5 text-right font-mono text-terminal-text-secondary">
                      {h.currency === "EUR" ? "—" : h.fxRate.toFixed(4)}
                    </td>
                    <td className="py-1.5 text-right font-mono">
                      <Private>{formatLargeNumber(h.marketValueEurCents)}</Private>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ── Helpers ── */

function FxChange({ value }: { value: number | null }) {
  if (value == null) return <span className="text-terminal-text-tertiary">—</span>;
  const color = value > 0 ? "text-terminal-positive" : value < 0 ? "text-terminal-negative" : "text-terminal-text-secondary";
  return <span className={color}>{formatPercent(value, true)}</span>;
}

function ImpactCell({ cents }: { cents: number | null }) {
  if (cents == null) return <span className="text-terminal-text-tertiary">—</span>;
  const color = cents >= 0 ? "text-terminal-positive" : "text-terminal-negative";
  return (
    <Private>
      <span className={color}>{formatCurrency(cents)}</span>
    </Private>
  );
}
