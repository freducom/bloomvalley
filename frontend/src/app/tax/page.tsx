"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGet, apiGetRaw } from "@/lib/api";
import { formatCurrency, formatPercent, formatDate } from "@/lib/format";
import { Private } from "@/lib/privacy";
import { TickerLink } from "@/components/ui/TickerLink";

/* ── Types ── */

interface TaxLot {
  id: number;
  accountId: number;
  accountName: string;
  accountType: string;
  securityId: number;
  ticker: string;
  securityName: string;
  assetClass: string | null;
  state: string;
  acquiredDate: string;
  closedDate: string | null;
  originalQuantity: string;
  remainingQuantity: string;
  costBasisCents: number;
  costBasisCurrency: string;
  proceedsCents: number | null;
  realizedPnlCents: number | null;
  marketValueCents: number | null;
  unrealizedPnlCents: number | null;
  holdingYears: number;
  actualGainCents?: number;
  deemedCostCents?: number;
  deemedGainCents?: number;
  taxableGainCents?: number;
  methodUsed?: string;
}

interface GainsData {
  year: number;
  realizedGainsCents: number;
  realizedLossesCents: number;
  netRealizedCents: number;
  estimatedTax: {
    taxCents: number;
    effectiveRate: number;
    bracket30kCents: number;
    bracketAboveCents: number;
  };
  byCategory: { category: string; gainsCents: number; lossesCents: number; netCents: number }[];
  perSecurity: {
    ticker: string;
    name: string;
    accountName: string;
    accountType: string;
    acquiredDate: string;
    closedDate: string | null;
    costBasisCents: number;
    proceedsCents: number | null;
    taxableGainCents?: number;
    methodUsed?: string;
    holdingYears?: number;
    isTaxFree: boolean;
  }[];
}

interface OstData {
  hasAccount: boolean;
  accountId?: number;
  accountName?: string;
  totalDepositsCents?: number;
  depositCapCents?: number;
  depositCapUsedPct?: number;
  currentValueCents?: number;
  gainsCents?: number;
  gainsRatio?: number;
  holdings?: { securityId: number; ticker: string; name: string; quantity: string; marketValueEurCents: number }[];
  depositHistory?: { date: string; amountCents: number; runningTotalCents: number }[];
}

interface HarvestingData {
  totalUnrealizedLossCents: number;
  realizedGainsYtdCents: number;
  potentialTaxSavingsCents: number;
  candidates: {
    lotId: number;
    securityId: number;
    ticker: string;
    name: string;
    accountName: string;
    quantity: string;
    costBasisCents: number;
    marketValueCents: number;
    unrealizedLossCents: number;
    holdingYears: number;
    taxSavingLowCents: number;
    taxSavingHighCents: number;
  }[];
}

type Tab = "lots" | "gains" | "ost" | "harvesting";

const STATE_COLORS: Record<string, string> = {
  open: "text-terminal-positive bg-terminal-positive/10 border-terminal-positive/30",
  partially_closed: "text-terminal-warning bg-terminal-warning/10 border-terminal-warning/30",
  closed: "text-terminal-text-secondary bg-terminal-bg-tertiary border-terminal-border",
};

export default function TaxPage() {
  const [tab, setTab] = useState<Tab>("lots");
  const [year, setYear] = useState(new Date().getFullYear());

  const tabs: { key: Tab; label: string }[] = [
    { key: "lots", label: "Tax Lots" },
    { key: "gains", label: "Gains" },
    { key: "ost", label: "OST" },
    { key: "harvesting", label: "Harvesting" },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Tax Management</h1>
        {(tab === "gains" || tab === "lots") && (
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
          >
            {[2026, 2025, 2024, 2023].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        )}
      </div>

      <div className="flex gap-1 mb-4 border-b border-terminal-border">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? "border-terminal-accent text-terminal-accent"
                : "border-transparent text-terminal-text-secondary hover:text-terminal-text-primary"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "lots" && <TaxLotsTab year={year} />}
      {tab === "gains" && <GainsTab year={year} />}
      {tab === "ost" && <OstTab />}
      {tab === "harvesting" && <HarvestingTab />}
    </div>
  );
}

/* ── Tax Lots Tab ── */

function TaxLotsTab({ year }: { year: number }) {
  const [lots, setLots] = useState<TaxLot[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filterState, setFilterState] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (filterState) params.set("state", filterState);
        params.set("limit", "500");
        const res = await apiGetRaw<{ data: TaxLot[]; pagination: { total: number } }>(
          `/tax/lots?${params}`
        );
        setLots(res.data);
        setTotal(res.pagination.total);
      } catch { /* */ }
      setLoading(false);
    })();
  }, [filterState, year]);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  return (
    <div>
      <div className="flex gap-3 mb-4">
        <select
          value={filterState}
          onChange={(e) => setFilterState(e.target.value)}
          className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
        >
          <option value="">All states</option>
          <option value="open">Open</option>
          <option value="partially_closed">Partially closed</option>
          <option value="closed">Closed</option>
        </select>
        <span className="text-sm text-terminal-text-secondary self-center">{total} lots</span>
      </div>

      <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
              <th className="text-left p-3">Security</th>
              <th className="text-left p-3">Account</th>
              <th className="text-center p-3">State</th>
              <th className="text-left p-3">Acquired</th>
              <th className="text-right p-3">Qty</th>
              <th className="text-right p-3">Cost Basis</th>
              <th className="text-right p-3">Market Value</th>
              <th className="text-right p-3">Unrealized</th>
              <th className="text-right p-3">Realized</th>
              <th className="text-right p-3">Years</th>
            </tr>
          </thead>
          <tbody>
            {lots.map((lot) => (
              <tr key={lot.id} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
                <td className="p-3">
                  <TickerLink ticker={lot.ticker} />
                </td>
                <td className="p-3 text-terminal-text-secondary text-xs">{lot.accountName}</td>
                <td className="text-center p-3">
                  <span className={`text-xs px-2 py-0.5 rounded border ${STATE_COLORS[lot.state] || ""}`}>
                    {lot.state.replace("_", " ")}
                  </span>
                </td>
                <td className="p-3 text-xs">{formatDate(lot.acquiredDate)}</td>
                <td className="text-right p-3 font-mono text-xs">
                  <Private>{parseFloat(lot.remainingQuantity).toLocaleString(undefined, { maximumFractionDigits: 4 })}</Private>
                </td>
                <td className="text-right p-3 font-mono text-xs">
                  <Private>{formatCurrency(lot.costBasisCents, lot.costBasisCurrency)}</Private>
                </td>
                <td className="text-right p-3 font-mono text-xs">
                  {lot.marketValueCents !== null ? <Private>{formatCurrency(lot.marketValueCents, lot.costBasisCurrency)}</Private> : "-"}
                </td>
                <td className={`text-right p-3 font-mono text-xs ${
                  lot.unrealizedPnlCents !== null
                    ? lot.unrealizedPnlCents >= 0 ? "text-terminal-positive" : "text-terminal-negative"
                    : ""
                }`}>
                  {lot.unrealizedPnlCents !== null ? <Private>{formatCurrency(lot.unrealizedPnlCents, lot.costBasisCurrency)}</Private> : "-"}
                </td>
                <td className={`text-right p-3 font-mono text-xs ${
                  lot.realizedPnlCents !== null
                    ? lot.realizedPnlCents >= 0 ? "text-terminal-positive" : "text-terminal-negative"
                    : ""
                }`}>
                  {lot.realizedPnlCents !== null ? <Private>{formatCurrency(lot.realizedPnlCents, lot.costBasisCurrency)}</Private> : "-"}
                </td>
                <td className="text-right p-3 font-mono text-xs text-terminal-text-secondary">
                  {lot.holdingYears.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Gains Tab ── */

function GainsTab({ year }: { year: number }) {
  const [data, setData] = useState<GainsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await apiGetRaw<{ data: GainsData }>(`/tax/gains?year=${year}`);
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, [year]);

  if (loading || !data) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  const threshold = 3_000_000;
  const netForBar = Math.max(0, data.netRealizedCents);
  const pctOf30k = Math.min(100, (netForBar / threshold) * 100);
  const pctAbove = netForBar > threshold ? Math.min(100, ((netForBar - threshold) / threshold) * 100) : 0;

  return (
    <div className="space-y-6">
      {/* Hero metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Realized Gains (YTD)" value={formatCurrency(data.realizedGainsCents)} valueClass="text-terminal-positive" isPrivate />
        <MetricCard label="Realized Losses (YTD)" value={formatCurrency(data.realizedLossesCents)} valueClass="text-terminal-negative" isPrivate />
        <MetricCard label="Net Realized P&L" value={formatCurrency(data.netRealizedCents)} valueClass={data.netRealizedCents >= 0 ? "text-terminal-positive" : "text-terminal-negative"} isPrivate />
        <MetricCard label="Estimated Tax" value={formatCurrency(data.estimatedTax.taxCents)} sub={`Effective rate: ${data.estimatedTax.effectiveRate}%`} isPrivate />
      </div>

      {/* Tax bracket bar */}
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
        <h3 className="text-sm font-semibold text-terminal-text-secondary mb-3">Tax Bracket Progress</h3>
        <div className="relative h-6 bg-terminal-bg-tertiary rounded overflow-hidden">
          <div
            className="absolute h-full bg-terminal-info/40 border-r border-terminal-info"
            style={{ width: `${Math.min(pctOf30k, 100)}%` }}
          />
          {pctAbove > 0 && (
            <div
              className="absolute h-full bg-terminal-warning/40"
              style={{ left: `${Math.min(pctOf30k, 100)}%`, width: `${pctAbove}%` }}
            />
          )}
          <div className="absolute inset-0 flex items-center justify-center text-xs font-mono text-terminal-text-primary">
            <Private>{formatCurrency(netForBar)}</Private> / {formatCurrency(threshold)}
          </div>
        </div>
        <div className="flex justify-between text-xs text-terminal-text-secondary mt-1">
          <span>30% rate</span>
          <span>{formatCurrency(threshold)} threshold</span>
          <span>34% rate</span>
        </div>
      </div>

      {/* By category */}
      {data.byCategory.length > 0 && (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-hidden">
          <h3 className="text-sm font-semibold text-terminal-text-secondary p-3 border-b border-terminal-border">
            Gains by Category
          </h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
                <th className="text-left p-3">Category</th>
                <th className="text-right p-3">Gains</th>
                <th className="text-right p-3">Losses</th>
                <th className="text-right p-3">Net</th>
              </tr>
            </thead>
            <tbody>
              {data.byCategory.map((cat) => (
                <tr key={cat.category} className="border-b border-terminal-border/50">
                  <td className="p-3 capitalize">{cat.category}</td>
                  <td className="text-right p-3 font-mono text-terminal-positive"><Private>{formatCurrency(cat.gainsCents)}</Private></td>
                  <td className="text-right p-3 font-mono text-terminal-negative"><Private>{formatCurrency(cat.lossesCents)}</Private></td>
                  <td className={`text-right p-3 font-mono ${cat.netCents >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                    <Private>{formatCurrency(cat.netCents)}</Private>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Per-security sales */}
      {data.perSecurity.length > 0 ? (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-hidden">
          <h3 className="text-sm font-semibold text-terminal-text-secondary p-3 border-b border-terminal-border">
            Realized Sales
          </h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
                <th className="text-left p-3">Security</th>
                <th className="text-left p-3">Account</th>
                <th className="text-left p-3">Acquired</th>
                <th className="text-left p-3">Closed</th>
                <th className="text-right p-3">Cost</th>
                <th className="text-right p-3">Proceeds</th>
                <th className="text-right p-3">Taxable Gain</th>
                <th className="text-center p-3">Method</th>
                <th className="text-center p-3">Tax-Free</th>
              </tr>
            </thead>
            <tbody>
              {data.perSecurity.map((s, i) => (
                <tr key={i} className="border-b border-terminal-border/50">
                  <td className="p-3"><TickerLink ticker={s.ticker} /></td>
                  <td className="p-3 text-xs text-terminal-text-secondary">{s.accountName}</td>
                  <td className="p-3 text-xs">{formatDate(s.acquiredDate)}</td>
                  <td className="p-3 text-xs">{s.closedDate ? formatDate(s.closedDate) : "-"}</td>
                  <td className="text-right p-3 font-mono text-xs"><Private>{formatCurrency(s.costBasisCents)}</Private></td>
                  <td className="text-right p-3 font-mono text-xs">{s.proceedsCents !== null ? <Private>{formatCurrency(s.proceedsCents)}</Private> : "-"}</td>
                  <td className={`text-right p-3 font-mono text-xs ${
                    (s.taxableGainCents || 0) >= 0 ? "text-terminal-positive" : "text-terminal-negative"
                  }`}>
                    {s.taxableGainCents !== undefined ? <Private>{formatCurrency(s.taxableGainCents)}</Private> : "-"}
                  </td>
                  <td className="text-center p-3 text-xs capitalize">{s.methodUsed || "-"}</td>
                  <td className="text-center p-3">
                    {s.isTaxFree && <span className="text-xs text-terminal-info">Yes</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
          <p className="text-terminal-text-secondary text-sm">
            No realized gains or losses in {year}. Sell positions to see tax impact here.
          </p>
        </div>
      )}
    </div>
  );
}

/* ── OST Tab ── */

function OstTab() {
  const [data, setData] = useState<OstData | null>(null);
  const [loading, setLoading] = useState(true);
  const [withdrawalPct, setWithdrawalPct] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: OstData }>("/tax/osakesaastotili");
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (!data?.hasAccount) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No osakesäästötili (equity savings account) found. Create one in the Accounts section.
        </p>
        <p className="text-xs text-terminal-text-secondary mt-2">
          Lifetime deposit cap: €50,000. Internal trades are tax-free. Tax only on withdrawal.
        </p>
      </div>
    );
  }

  const withdrawalAmount = Math.round((data.currentValueCents || 0) * withdrawalPct / 100);
  const gainsRatio = (data.gainsRatio || 0) / 100;
  const taxablePortion = Math.round(withdrawalAmount * gainsRatio);
  const taxFreePortion = withdrawalAmount - taxablePortion;
  const taxOnWithdrawal = _computeTaxFrontend(taxablePortion);

  return (
    <div className="space-y-6">
      {/* Banner */}
      <div className="bg-terminal-info/10 border border-terminal-info/30 rounded p-3 text-sm text-terminal-info">
        Internal trades within OST are not taxable events. Tax is calculated only on withdrawal.
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Total Deposits"
          value={formatCurrency(data.totalDepositsCents || 0)}
          sub={`${data.depositCapUsedPct}% of €50,000 cap`}
          isPrivate
        />
        <MetricCard label="Current Value" value={formatCurrency(data.currentValueCents || 0)} isPrivate />
        <MetricCard
          label="Gains"
          value={formatCurrency(data.gainsCents || 0)}
          valueClass={(data.gainsCents || 0) >= 0 ? "text-terminal-positive" : "text-terminal-negative"}
          isPrivate
        />
        <MetricCard label="Gains Ratio" value={`${data.gainsRatio}%`} sub="Taxable portion of withdrawals" />
      </div>

      {/* Deposit cap progress */}
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
        <h3 className="text-sm font-semibold text-terminal-text-secondary mb-2">Deposit Cap</h3>
        <div className="relative h-4 bg-terminal-bg-tertiary rounded overflow-hidden">
          <div
            className="h-full bg-terminal-accent/60 rounded"
            style={{ width: `${data.depositCapUsedPct}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-terminal-text-secondary mt-1">
          <span><Private>{formatCurrency(data.totalDepositsCents || 0)}</Private> deposited</span>
          <span><Private>{formatCurrency((data.depositCapCents || 0) - (data.totalDepositsCents || 0))}</Private> remaining</span>
        </div>
      </div>

      {/* Withdrawal calculator */}
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
        <h3 className="text-sm font-semibold text-terminal-text-secondary mb-3">Withdrawal Tax Calculator</h3>
        <div className="flex items-center gap-4 mb-3">
          <input
            type="range"
            min={0}
            max={100}
            value={withdrawalPct}
            onChange={(e) => setWithdrawalPct(Number(e.target.value))}
            className="flex-1 accent-terminal-accent"
          />
          <span className="font-mono text-sm w-32 text-right">
            <Private>{formatCurrency(withdrawalAmount)}</Private>
          </span>
        </div>
        {withdrawalPct > 0 && (
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <div className="text-xs text-terminal-text-secondary">Taxable portion</div>
              <div className="font-mono text-terminal-warning"><Private>{formatCurrency(taxablePortion)}</Private></div>
            </div>
            <div>
              <div className="text-xs text-terminal-text-secondary">Tax-free portion</div>
              <div className="font-mono text-terminal-positive"><Private>{formatCurrency(taxFreePortion)}</Private></div>
            </div>
            <div>
              <div className="text-xs text-terminal-text-secondary">Estimated tax</div>
              <div className="font-mono text-terminal-negative"><Private>{formatCurrency(taxOnWithdrawal)}</Private></div>
            </div>
          </div>
        )}
      </div>

      {/* Holdings */}
      {data.holdings && data.holdings.length > 0 && (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-hidden">
          <h3 className="text-sm font-semibold text-terminal-text-secondary p-3 border-b border-terminal-border">
            OST Holdings
          </h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
                <th className="text-left p-3">Security</th>
                <th className="text-right p-3">Quantity</th>
                <th className="text-right p-3">Market Value</th>
              </tr>
            </thead>
            <tbody>
              {data.holdings.map((h) => (
                <tr key={h.securityId} className="border-b border-terminal-border/50">
                  <td className="p-3">
                    <TickerLink ticker={h.ticker} className="font-mono text-terminal-accent mr-2 hover:underline" />
                    <span className="text-xs text-terminal-text-secondary">{h.name}</span>
                  </td>
                  <td className="text-right p-3 font-mono text-xs">
                    <Private>{parseFloat(h.quantity).toLocaleString(undefined, { maximumFractionDigits: 4 })}</Private>
                  </td>
                  <td className="text-right p-3 font-mono text-xs"><Private>{formatCurrency(h.marketValueEurCents)}</Private></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── Harvesting Tab ── */

function HarvestingTab() {
  const [data, setData] = useState<HarvestingData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: HarvestingData }>("/tax/harvesting");
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;
  if (!data) return null;

  return (
    <div className="space-y-6">
      {/* Warning */}
      <div className="bg-terminal-warning/10 border border-terminal-warning/30 rounded p-3 text-sm text-terminal-warning">
        Loss harvesting involves selling a position to realize a loss. Finnish tax law does not have an explicit wash sale rule, but substance-over-form doctrine applies.
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Total Unrealized Losses"
          value={formatCurrency(data.totalUnrealizedLossCents)}
          valueClass="text-terminal-negative"
          isPrivate
        />
        <MetricCard label="Realized Gains YTD" value={formatCurrency(data.realizedGainsYtdCents)} valueClass="text-terminal-positive" isPrivate />
        <MetricCard label="Potential Tax Savings" value={formatCurrency(data.potentialTaxSavingsCents)} valueClass="text-terminal-info" isPrivate />
        <MetricCard label="Harvesting Budget" value={formatCurrency(data.realizedGainsYtdCents)} sub="Gains to offset" isPrivate />
      </div>

      {/* Candidates */}
      {data.candidates.length > 0 ? (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-hidden">
          <h3 className="text-sm font-semibold text-terminal-text-secondary p-3 border-b border-terminal-border">
            Harvesting Candidates
          </h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
                <th className="text-left p-3">Security</th>
                <th className="text-left p-3">Account</th>
                <th className="text-right p-3">Quantity</th>
                <th className="text-right p-3">Cost Basis</th>
                <th className="text-right p-3">Market Value</th>
                <th className="text-right p-3">Unrealized Loss</th>
                <th className="text-right p-3">Years</th>
                <th className="text-right p-3">Tax Saving</th>
              </tr>
            </thead>
            <tbody>
              {data.candidates.map((c) => (
                <tr key={c.lotId} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
                  <td className="p-3">
                    <TickerLink ticker={c.ticker} className="font-mono text-terminal-accent mr-2 hover:underline" />
                    <span className="text-xs text-terminal-text-secondary">{c.name}</span>
                  </td>
                  <td className="p-3 text-xs text-terminal-text-secondary">{c.accountName}</td>
                  <td className="text-right p-3 font-mono text-xs">
                    <Private>{parseFloat(c.quantity).toLocaleString(undefined, { maximumFractionDigits: 4 })}</Private>
                  </td>
                  <td className="text-right p-3 font-mono text-xs"><Private>{formatCurrency(c.costBasisCents)}</Private></td>
                  <td className="text-right p-3 font-mono text-xs"><Private>{formatCurrency(c.marketValueCents)}</Private></td>
                  <td className="text-right p-3 font-mono text-xs text-terminal-negative">
                    <Private>{formatCurrency(c.unrealizedLossCents)}</Private>
                  </td>
                  <td className="text-right p-3 font-mono text-xs text-terminal-text-secondary">
                    {c.holdingYears.toFixed(1)}
                  </td>
                  <td className="text-right p-3 font-mono text-xs text-terminal-info">
                    <Private>{formatCurrency(c.taxSavingLowCents)}&ndash;{formatCurrency(c.taxSavingHighCents)}</Private>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
          <p className="text-terminal-text-secondary text-sm">
            No loss harvesting candidates. All open positions in taxable accounts have unrealized gains.
          </p>
        </div>
      )}
    </div>
  );
}

/* ── Helpers ── */

function MetricCard({ label, value, valueClass, sub, isPrivate }: { label: string; value: string; valueClass?: string; sub?: string; isPrivate?: boolean }) {
  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
      <div className="text-xs text-terminal-text-secondary mb-1">{label}</div>
      <div className={`text-lg font-mono font-bold ${valueClass || "text-terminal-text-primary"}`}>{isPrivate ? <Private>{value}</Private> : value}</div>
      {sub && <div className="text-xs text-terminal-text-secondary mt-0.5">{sub}</div>}
    </div>
  );
}

function _computeTaxFrontend(cents: number): number {
  if (cents <= 0) return 0;
  if (cents <= 3_000_000) return Math.round(cents * 0.30);
  return Math.round(3_000_000 * 0.30 + (cents - 3_000_000) * 0.34);
}
