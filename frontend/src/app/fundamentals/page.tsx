"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGetRaw } from "@/lib/api";
import { formatCurrency, formatDate, formatPercent, formatLargeNumber } from "@/lib/format";
import { TickerLink } from "@/components/ui/TickerLink";
import { InfoTip } from "@/components/ui/InfoTip";
import { PriceWithDate } from "@/components/ui/PriceWithDate";

/* ── Types ── */

interface Fundamentals {
  id: number;
  securityId: number;
  ticker: string;
  securityName: string;
  assetClass: string;
  currency: string;
  priceToBook: number | null;
  freeCashFlowCents: number | null;
  fcfCurrency: string | null;
  dcfValueCents: number | null;
  dcfPerShareCents: number | null;
  dcfDiscountRate: number | null;
  dcfTerminalGrowth: number | null;
  dcfModelNotes: string | null;
  dcfUpsidePct: number | null;
  currentPriceCents: number | null;
  shortInterestPct: number | null;
  shortInterestChangePct: number | null;
  shortSqueezeRisk: string | null;
  daysToCover: number | null;
  institutionalOwnershipPct: number | null;
  institutionalFlow: string | null;
  smartMoneySignal: string | null;
  smartMoneyOutlookDays: number | null;
  // Quality & profitability
  roic: number | null;
  wacc: number | null;
  roe: number | null;
  fcfYield: number | null;
  netDebtEbitda: number | null;
  dividendYield: number | null;
  epsCents: number | null;
  revenueCents: number | null;
  grossMargin: number | null;
  operatingMargin: number | null;
  netMargin: number | null;
  peRatio: number | null;
  marketCapCents: number | null;
  updatedAt: string;
}

interface EarningsReport {
  id: number;
  securityId: number;
  ticker: string | null;
  securityName: string | null;
  fiscalQuarter: string;
  fiscalYear: number;
  quarter: number;
  reportDate: string | null;
  revenueCents: number | null;
  revenueCurrency: string | null;
  revenueYoyPct: number | null;
  epsCents: number | null;
  epsYoyPct: number | null;
  grossMarginPct: number | null;
  operatingMarginPct: number | null;
  forwardGuidance: string | null;
  redFlags: string | null;
  recommendation: string | null;
  recommendationReasoning: string | null;
  source: string | null;
  updatedAt: string;
}

type Tab = "overview" | "dcf" | "shorts" | "smartmoney" | "earnings";

const REC_COLORS: Record<string, string> = {
  buy: "text-terminal-positive bg-terminal-positive/10",
  hold: "text-terminal-warning bg-terminal-warning/10",
  sell: "text-terminal-negative bg-terminal-negative/10",
};

const FLOW_COLORS: Record<string, string> = {
  accumulating: "text-terminal-positive",
  distributing: "text-terminal-negative",
  neutral: "text-terminal-text-secondary",
};

const SQUEEZE_COLORS: Record<string, string> = {
  high: "text-terminal-negative bg-terminal-negative/10",
  medium: "text-terminal-warning bg-terminal-warning/10",
  low: "text-terminal-text-secondary bg-terminal-bg-tertiary",
};

export default function FundamentalsPage() {
  const [tab, setTab] = useState<Tab>("overview");

  const tabs: { key: Tab; label: string; tooltip?: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "dcf", label: "DCF Valuations", tooltip: "Discounted Cash Flow valuations. Estimates intrinsic value by projecting future cash flows and discounting them back to present value." },
    { key: "shorts", label: "Short Interest", tooltip: "Short selling data. Shows how many shares are being bet against — can signal bearish sentiment or contrarian opportunity." },
    { key: "smartmoney", label: "Smart Money", tooltip: "Institutional ownership tracking. Monitors positions of hedge funds and superinvestors for conviction signals." },
    { key: "earnings", label: "Earnings" },
  ];

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Fundamentals</h1>
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
            {t.label}{t.tooltip && <> <InfoTip text={t.tooltip} /></>}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab />}
      {tab === "dcf" && <DcfTab />}
      {tab === "shorts" && <ShortsTab />}
      {tab === "smartmoney" && <SmartMoneyTab />}
      {tab === "earnings" && <EarningsTab />}
    </div>
  );
}

/* ── Overview: All fundamentals in one table ── */

type SortKey = "ticker" | "currentPriceCents" | "priceToBook" | "peRatio" | "roic" | "fcfYield" | "netDebtEbitda" | "dividendYield" | "grossMargin" | "operatingMargin" | "dcfUpsidePct" | "shortInterestPct" | "updatedAt";

interface Filters {
  preset: string;
  assetClass: string;
  minRoic: string;
  maxPb: string;
  maxPe: string;
  maxDebt: string;
  minFcfYield: string;
  minGrossMargin: string;
  hideMissing: boolean;
}

const DEFAULT_FILTERS: Filters = {
  preset: "",
  assetClass: "",
  minRoic: "",
  maxPb: "",
  maxPe: "",
  maxDebt: "",
  minFcfYield: "",
  minGrossMargin: "",
  hideMissing: false,
};

const PRESETS: { key: string; label: string; filters: Partial<Filters> }[] = [
  { key: "compounders", label: "Quality Compounders", filters: { minRoic: "0.15", minGrossMargin: "0.15", maxDebt: "3" } },
  { key: "value", label: "Value", filters: { maxPe: "20", maxPb: "2", minFcfYield: "0.04" } },
  { key: "dividend", label: "Dividend", filters: { minRoic: "0.10" } },
  { key: "undervalued", label: "Undervalued (DCF)", filters: {} },
  { key: "lowdebt", label: "Low Debt", filters: { maxDebt: "1" } },
];

function applyFilters(data: Fundamentals[], filters: Filters): Fundamentals[] {
  return data.filter((f) => {
    if (filters.assetClass && f.assetClass !== filters.assetClass) return false;

    if (filters.minRoic) {
      const min = parseFloat(filters.minRoic);
      if (f.roic === null || f.roic < min) return false;
    }
    if (filters.maxPb) {
      const max = parseFloat(filters.maxPb);
      if (f.priceToBook === null || f.priceToBook > max) return false;
    }
    if (filters.maxPe) {
      const max = parseFloat(filters.maxPe);
      if (f.peRatio === null || f.peRatio > max) return false;
    }
    if (filters.maxDebt) {
      const max = parseFloat(filters.maxDebt);
      // Allow negative (net cash) — only filter out if > max
      if (f.netDebtEbitda === null || f.netDebtEbitda > max) return false;
    }
    if (filters.minFcfYield) {
      const min = parseFloat(filters.minFcfYield);
      if (f.fcfYield === null || f.fcfYield < min) return false;
    }
    if (filters.minGrossMargin) {
      const min = parseFloat(filters.minGrossMargin);
      // For gross margin, compare as ratio (operatingMargin for "compounders" preset uses this too)
      if (f.grossMargin === null || f.grossMargin < min) return false;
    }

    // Dividend preset: must have dividend yield > 2%
    if (filters.preset === "dividend") {
      if (f.dividendYield === null || f.dividendYield < 0.02) return false;
    }

    // Undervalued preset: must have DCF upside > 20%
    if (filters.preset === "undervalued") {
      if (f.dcfUpsidePct === null || f.dcfUpsidePct < 20) return false;
    }

    if (filters.hideMissing) {
      if (f.roic === null && f.peRatio === null && f.priceToBook === null) return false;
    }

    return true;
  });
}

function OverviewTab() {
  const [data, setData] = useState<Fundamentals[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("roic");
  const [sortAsc, setSortAsc] = useState(false);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: Fundamentals[] }>("/fundamentals?limit=500");
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  const setFilter = (key: keyof Filters, value: string | boolean) => {
    setFilters((prev) => ({ ...prev, preset: key === "preset" ? (value as string) : prev.preset, [key]: value }));
  };

  const applyPreset = (presetKey: string) => {
    if (filters.preset === presetKey) {
      // Toggle off
      setFilters(DEFAULT_FILTERS);
      return;
    }
    const preset = PRESETS.find((p) => p.key === presetKey);
    if (!preset) return;
    setFilters({ ...DEFAULT_FILTERS, preset: presetKey, ...preset.filters });
  };

  const clearFilters = () => setFilters(DEFAULT_FILTERS);
  const hasActiveFilters = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const filtered = applyFilters(data, filters);

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey] ?? (sortAsc ? Infinity : -Infinity);
    const bv = b[sortKey] ?? (sortAsc ? Infinity : -Infinity);
    if (typeof av === "string" && typeof bv === "string") return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  const arrow = (key: SortKey) => sortKey === key ? (sortAsc ? " ▲" : " ▼") : "";

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (data.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No fundamentals data yet. Agent analysts can populate DCF, P/B, short interest, and smart money data via the API.
        </p>
      </div>
    );
  }

  const SEL = "bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1 text-xs text-terminal-text-primary";

  const TH = ({ k, align, title, children }: { k: SortKey; align?: string; title: string; children: React.ReactNode }) => (
    <th
      className={`${align || "text-right"} p-3 cursor-pointer select-none hover:text-terminal-accent transition-colors whitespace-nowrap`}
      title={title}
      onClick={() => handleSort(k)}
    >
      {children}{arrow(k)}
    </th>
  );

  return (
    <div>
      {/* Preset screens */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            onClick={() => applyPreset(p.key)}
            className={`px-3 py-1.5 text-xs font-medium rounded border transition-colors ${
              filters.preset === p.key
                ? "bg-terminal-accent/20 text-terminal-accent border-terminal-accent/50"
                : "bg-terminal-bg-secondary text-terminal-text-secondary border-terminal-border hover:text-terminal-text-primary hover:border-terminal-text-tertiary"
            }`}
          >
            {p.label}
          </button>
        ))}
        {hasActiveFilters && (
          <button onClick={clearFilters} className="px-2 py-1.5 text-xs text-terminal-text-tertiary hover:text-terminal-negative transition-colors">
            Clear filters
          </button>
        )}
      </div>

      {/* Column filters */}
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <select value={filters.assetClass} onChange={(e) => setFilter("assetClass", e.target.value)} className={SEL}>
          <option value="">All classes</option>
          <option value="stock">Stocks</option>
          <option value="etf">ETFs</option>
          <option value="crypto">Crypto</option>
        </select>

        <select value={filters.minRoic} onChange={(e) => setFilter("minRoic", e.target.value)} className={SEL}>
          <option value="">ROIC: any</option>
          <option value="0.10">&gt; 10%</option>
          <option value="0.15">&gt; 15%</option>
          <option value="0.20">&gt; 20%</option>
          <option value="0.30">&gt; 30%</option>
        </select>

        <select value={filters.maxPb} onChange={(e) => setFilter("maxPb", e.target.value)} className={SEL}>
          <option value="">P/B: any</option>
          <option value="1">&lt; 1</option>
          <option value="2">&lt; 2</option>
          <option value="3">&lt; 3</option>
          <option value="5">&lt; 5</option>
        </select>

        <select value={filters.maxPe} onChange={(e) => setFilter("maxPe", e.target.value)} className={SEL}>
          <option value="">P/E: any</option>
          <option value="15">&lt; 15</option>
          <option value="20">&lt; 20</option>
          <option value="30">&lt; 30</option>
          <option value="50">&lt; 50</option>
        </select>

        <select value={filters.maxDebt} onChange={(e) => setFilter("maxDebt", e.target.value)} className={SEL}>
          <option value="">Debt: any</option>
          <option value="0">&lt; 0x (net cash)</option>
          <option value="1">&lt; 1x</option>
          <option value="2">&lt; 2x</option>
          <option value="3">&lt; 3x</option>
        </select>

        <select value={filters.minFcfYield} onChange={(e) => setFilter("minFcfYield", e.target.value)} className={SEL}>
          <option value="">FCF Yield: any</option>
          <option value="0.03">&gt; 3%</option>
          <option value="0.05">&gt; 5%</option>
          <option value="0.08">&gt; 8%</option>
        </select>

        <select value={filters.minGrossMargin} onChange={(e) => setFilter("minGrossMargin", e.target.value)} className={SEL}>
          <option value="">Gross Margin: any</option>
          <option value="0.30">&gt; 30%</option>
          <option value="0.50">&gt; 50%</option>
          <option value="0.70">&gt; 70%</option>
        </select>

        <label className="flex items-center gap-1.5 text-xs text-terminal-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={filters.hideMissing}
            onChange={(e) => setFilter("hideMissing", e.target.checked)}
            className="rounded border-terminal-border"
          />
          Hide missing
        </label>
      </div>

      {/* Result count */}
      <div className="text-xs text-terminal-text-tertiary mb-2">
        {filtered.length} of {data.length} securities
      </div>

    <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto max-h-[80vh] overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-terminal-bg-secondary">
          <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
            <TH k="ticker" align="text-left" title="Company ticker and name">Security</TH>
            <TH k="currentPriceCents" title="Current market price per share">Price</TH>
            <TH k="priceToBook" title="Price-to-Book ratio. Useful for banks, industrials, asset-heavy businesses. Less meaningful for software/asset-light companies.">P/B <InfoTip text="Price-to-Book ratio. Compares market price to book value. Below 1.0 may indicate undervaluation; above 3.0 is typical for high-quality businesses." /></TH>
            <TH k="peRatio" title="Price-to-Earnings ratio. Lower = cheaper relative to earnings. Compare within sector, not across sectors.">PE <InfoTip text="Price-to-Earnings ratio. Share price divided by earnings per share. Lower P/E may indicate undervaluation, but compare within the same sector." /></TH>
            <TH k="roic" title="Return on Invested Capital. The most important quality metric. A company returning above its WACC (~8-12%) is creating value. >15% = excellent, 10-15% = good, <10% = weak.">ROIC <InfoTip text="Return on Invested Capital. Measures how efficiently a company generates profits from its invested capital. Above 15% suggests a competitive moat." /></TH>
            <TH k="fcfYield" title="Free Cash Flow Yield = FCF / Market Cap. Higher means more cash generation per EUR invested. >5% is attractive.">FCF Yield <InfoTip text="Free Cash Flow yield. Cash generated after capex as a percentage of market cap. Higher yields mean more cash for shareholders." /></TH>
            <TH k="netDebtEbitda" title="Net Debt / EBITDA. Measures leverage. <1x = conservative, 1-3x = moderate, >3x = risky. Negative means net cash position.">Debt/EBITDA <InfoTip text="Leverage ratio. How many years of operating earnings needed to repay net debt. Below 2x is conservative; above 4x is high leverage." /></TH>
            <TH k="dividendYield" title="Annual dividend yield. Dividend payers are a positive signal. Growing importance as portfolio ages toward income focus.">Div Yield <InfoTip text="Annual dividend per share divided by share price. Measures income return on an investment." /></TH>
            <TH k="grossMargin" title="Gross margin — revenue minus cost of goods sold. Higher = stronger pricing power and competitive advantage.">Gross Mgn <InfoTip text="Revenue minus cost of goods sold, as a percentage of revenue. Higher margins indicate pricing power and efficiency." /></TH>
            <TH k="operatingMargin" title="Operating margin — profit from core operations. Higher = more efficient business. Key profitability indicator.">Op Mgn <InfoTip text="Operating income as a percentage of revenue. Measures core business profitability before interest and taxes." /></TH>
            <TH k="dcfUpsidePct" title="DCF (Discounted Cash Flow) upside/downside vs current market cap. Positive = undervalued. A high-ROIC company with large DCF upside is the strongest buy signal.">DCF Upside <InfoTip text="Discounted Cash Flow upside. Difference between the DCF-derived intrinsic value and the current market price. Positive = undervalued." /></TH>
            <TH k="shortInterestPct" title="Short interest as % of float. High short interest can signal bearish sentiment or potential squeeze. Less important than fundamentals.">Short % <InfoTip text="Percentage of shares outstanding currently sold short. High short interest (>10%) signals bearish sentiment or potential squeeze risk." /></TH>
            <th className="text-center p-3" title="Smart money signal from institutional flow and insider patterns. Supplementary indicator — less important than ROIC and DCF.">Smart Money <InfoTip text="Institutional ownership signals. Tracks whether sophisticated investors (hedge funds, superinvestors) are buying or selling." /></th>
            <TH k="updatedAt" align="text-left" title="Last time fundamentals data was updated">Updated</TH>
          </tr>
        </thead>
        <tbody>
          {sorted.map((f) => (
            <tr key={f.id} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
              <td className="p-3">
                <TickerLink ticker={f.ticker} className="font-mono text-terminal-accent mr-2 hover:underline" />
                <span className="text-xs text-terminal-text-secondary">{f.securityName}</span>
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {f.currentPriceCents ? <PriceWithDate date={f.updatedAt}>{formatCurrency(f.currentPriceCents, f.currency)}</PriceWithDate> : "-"}
              </td>
              <td className={`text-right p-3 font-mono text-xs ${
                f.priceToBook !== null && f.priceToBook < 1 ? "text-terminal-positive" :
                f.priceToBook !== null && f.priceToBook > 3 ? "text-terminal-warning" : ""
              }`}>
                {f.priceToBook !== null ? f.priceToBook.toFixed(2) : "-"}
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {f.peRatio !== null ? f.peRatio.toFixed(1) : "-"}
              </td>
              <td className={`text-right p-3 font-mono text-xs ${
                f.roic !== null
                  ? f.roic > 0.15 ? "text-terminal-positive" : f.roic >= 0.10 ? "text-terminal-warning" : "text-terminal-negative"
                  : ""
              }`}>
                {f.roic !== null ? formatPercent(f.roic * 100) : "-"}
              </td>
              <td className={`text-right p-3 font-mono text-xs ${
                f.fcfYield !== null && f.fcfYield > 0.05 ? "text-terminal-positive" : ""
              }`}>
                {f.fcfYield !== null ? formatPercent(f.fcfYield * 100) : "-"}
              </td>
              <td className={`text-right p-3 font-mono text-xs ${
                f.netDebtEbitda !== null && f.netDebtEbitda > 3 ? "text-terminal-negative" : ""
              }`}>
                {f.netDebtEbitda !== null ? `${f.netDebtEbitda.toFixed(1)}x` : "-"}
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {f.dividendYield !== null ? formatPercent(f.dividendYield * 100) : "-"}
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {f.grossMargin !== null ? formatPercent(f.grossMargin * 100) : "-"}
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {f.operatingMargin !== null ? formatPercent(f.operatingMargin * 100) : "-"}
              </td>
              <td className={`text-right p-3 font-mono text-xs font-medium ${
                f.dcfUpsidePct !== null
                  ? f.dcfUpsidePct >= 0 ? "text-terminal-positive" : "text-terminal-negative"
                  : ""
              }`}>
                {f.dcfUpsidePct !== null ? formatPercent(f.dcfUpsidePct, true) : "-"}
              </td>
              <td className={`text-right p-3 font-mono text-xs ${
                f.shortInterestPct !== null && f.shortInterestPct > 10 ? "text-terminal-warning" : ""
              }`}>
                {f.shortInterestPct !== null ? `${f.shortInterestPct.toFixed(2)}%` : "-"}
              </td>
              <td className="text-center p-3">
                {f.institutionalFlow && (
                  <span className={`text-xs capitalize ${FLOW_COLORS[f.institutionalFlow] || ""}`}>
                    {f.institutionalFlow}
                  </span>
                )}
              </td>
              <td className="p-3 text-xs text-terminal-text-secondary">{formatDate(f.updatedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </div>
  );
}

/* ── DCF Valuations Tab ── */

function DcfTab() {
  const [data, setData] = useState<Fundamentals[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: Fundamentals[] }>("/fundamentals?hasDcf=true&limit=500");
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (data.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No DCF valuations yet. DCF models use Free Cash Flow and are updated when FCF changes.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {data.map((f) => (
        <div key={f.id} className="border border-terminal-border rounded bg-terminal-bg-secondary">
          <div
            className="flex items-center gap-3 p-4 cursor-pointer hover:bg-terminal-bg-tertiary"
            onClick={() => setExpanded(expanded === f.id ? null : f.id)}
          >
            <TickerLink ticker={f.ticker} />
            <span className="text-xs text-terminal-text-secondary">{f.securityName}</span>
            <div className="ml-auto flex items-center gap-6">
              <div className="text-right">
                <span className="text-xs text-terminal-text-secondary block">Current</span>
                <span className="font-mono text-sm">{f.currentPriceCents ? <PriceWithDate date={f.updatedAt}>{formatCurrency(f.currentPriceCents, f.currency)}</PriceWithDate> : "-"}</span>
              </div>
              <div className="text-right">
                <span className="text-xs text-terminal-text-secondary block">DCF / Share</span>
                <span className="font-mono text-sm">{f.dcfPerShareCents ? formatCurrency(f.dcfPerShareCents, f.currency) : "-"}</span>
              </div>
              <div className="text-right">
                <span className="text-xs text-terminal-text-secondary block">Upside</span>
                <span className={`font-mono text-sm font-medium ${
                  f.dcfUpsidePct !== null
                    ? f.dcfUpsidePct >= 0 ? "text-terminal-positive" : "text-terminal-negative"
                    : ""
                }`}>
                  {f.dcfUpsidePct !== null ? formatPercent(f.dcfUpsidePct, true) : "-"}
                </span>
              </div>
              {f.priceToBook !== null && (
                <div className="text-right">
                  <span className="text-xs text-terminal-text-secondary block">P/B</span>
                  <span className="font-mono text-sm">{f.priceToBook.toFixed(2)}</span>
                </div>
              )}
            </div>
          </div>

          {expanded === f.id && (
            <div className="border-t border-terminal-border p-4 space-y-3">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                <div>
                  <span className="text-terminal-text-secondary">FCF</span>
                  <p className="font-mono">{f.freeCashFlowCents ? formatLargeNumber(f.freeCashFlowCents, f.fcfCurrency || f.currency) : "-"}</p>
                </div>
                <div>
                  <span className="text-terminal-text-secondary">Discount Rate</span>
                  <p className="font-mono">{f.dcfDiscountRate !== null ? `${(f.dcfDiscountRate * 100).toFixed(1)}%` : "-"}</p>
                </div>
                <div>
                  <span className="text-terminal-text-secondary">Terminal Growth</span>
                  <p className="font-mono">{f.dcfTerminalGrowth !== null ? `${(f.dcfTerminalGrowth * 100).toFixed(1)}%` : "-"}</p>
                </div>
                <div>
                  <span className="text-terminal-text-secondary">P/B Ratio</span>
                  <p className="font-mono">{f.priceToBook !== null ? f.priceToBook.toFixed(2) : "-"}</p>
                </div>
              </div>
              {f.dcfModelNotes && (
                <div>
                  <span className="text-xs text-terminal-text-secondary">Model Notes</span>
                  <p className="text-sm text-terminal-text-primary mt-1">{f.dcfModelNotes}</p>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ── Short Interest Tab ── */

function ShortsTab() {
  const [data, setData] = useState<Fundamentals[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: Fundamentals[] }>("/fundamentals?hasShortInterest=true&limit=500");
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (data.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No short interest data. Agents can populate short interest, days to cover, and squeeze risk via the API.
        </p>
      </div>
    );
  }

  // Sort by short interest descending
  const sorted = [...data].sort((a, b) => (b.shortInterestPct || 0) - (a.shortInterestPct || 0));

  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto max-h-[80vh] overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-terminal-bg-secondary">
          <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
            <th className="text-left p-3">Security</th>
            <th className="text-right p-3" title="Shares sold short as % of float. Higher = more bearish bets against the stock.">Short % Float</th>
            <th className="text-right p-3" title="Recent change in short interest. Increasing shorts = growing bearish sentiment.">Change</th>
            <th className="text-right p-3" title="Trading days needed for all shorts to cover. Higher = shorts are more trapped.">Days to Cover</th>
            <th className="text-center p-3" title="Risk of a short squeeze — when shorts are forced to buy back, pushing price up rapidly.">Squeeze Risk</th>
            <th className="text-right p-3">Price</th>
            <th className="text-left p-3">Updated</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((f) => (
            <tr key={f.id} className={`border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary ${
              f.shortSqueezeRisk === "high" ? "bg-terminal-warning/5" : ""
            }`}>
              <td className="p-3">
                <TickerLink ticker={f.ticker} className="font-mono text-terminal-accent mr-2 hover:underline" />
                <span className="text-xs text-terminal-text-secondary">{f.securityName}</span>
              </td>
              <td className={`text-right p-3 font-mono text-xs font-medium ${
                (f.shortInterestPct || 0) > 10 ? "text-terminal-warning" : ""
              }`}>
                {f.shortInterestPct !== null ? `${f.shortInterestPct.toFixed(2)}%` : "-"}
              </td>
              <td className={`text-right p-3 font-mono text-xs ${
                f.shortInterestChangePct !== null
                  ? f.shortInterestChangePct > 0 ? "text-terminal-negative" : "text-terminal-positive"
                  : ""
              }`}>
                {f.shortInterestChangePct !== null ? formatPercent(f.shortInterestChangePct, true) : "-"}
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {f.daysToCover !== null ? f.daysToCover.toFixed(1) : "-"}
              </td>
              <td className="text-center p-3">
                {f.shortSqueezeRisk && (
                  <span className={`text-xs px-2 py-0.5 rounded capitalize ${SQUEEZE_COLORS[f.shortSqueezeRisk] || ""}`}>
                    {f.shortSqueezeRisk}
                  </span>
                )}
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {f.currentPriceCents ? <PriceWithDate date={f.updatedAt}>{formatCurrency(f.currentPriceCents, f.currency)}</PriceWithDate> : "-"}
              </td>
              <td className="p-3 text-xs text-terminal-text-secondary">{formatDate(f.updatedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Smart Money Tab ── */

function SmartMoneyTab() {
  const [data, setData] = useState<Fundamentals[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: Fundamentals[] }>("/fundamentals?limit=500");
        setData(res.data.filter((f) => f.institutionalFlow || f.smartMoneySignal));
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (data.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No smart money data. Agents analyze institutional flows and provide 90-day outlook signals.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {data.map((f) => (
        <div key={f.id} className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <TickerLink ticker={f.ticker} />
              <span className="text-xs text-terminal-text-secondary">{f.securityName}</span>
            </div>
            <div className="flex items-center gap-4">
              {f.institutionalOwnershipPct !== null && (
                <span className="text-xs text-terminal-text-secondary">
                  Institutional: {f.institutionalOwnershipPct.toFixed(1)}%
                </span>
              )}
              {f.institutionalFlow && (
                <span className={`text-xs px-2 py-0.5 rounded capitalize font-medium ${FLOW_COLORS[f.institutionalFlow] || ""}`}>
                  {f.institutionalFlow}
                </span>
              )}
            </div>
          </div>
          {f.smartMoneySignal && (
            <p className="text-sm text-terminal-text-primary">
              <span className="text-xs text-terminal-text-secondary mr-1">
                {f.smartMoneyOutlookDays || 90}d outlook:
              </span>
              {f.smartMoneySignal}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/* ── Earnings Tab ── */

function EarningsTab() {
  const [reports, setReports] = useState<EarningsReport[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: EarningsReport[]; pagination: { total: number } }>(
          "/fundamentals/earnings?limit=200"
        );
        setReports(res.data);
        setTotal(res.pagination.total);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (reports.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No earnings reports yet. Agents analyze quarterly earnings with revenue, EPS, margins, guidance, and recommendations.
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm text-terminal-text-secondary mb-3">{total} earnings report{total !== 1 ? "s" : ""}</p>
      <div className="space-y-3">
        {reports.map((r) => (
          <div key={r.id} className="border border-terminal-border rounded bg-terminal-bg-secondary">
            <div
              className="flex items-center gap-3 p-4 cursor-pointer hover:bg-terminal-bg-tertiary"
              onClick={() => setExpanded(expanded === r.id ? null : r.id)}
            >
              {r.ticker && <TickerLink ticker={r.ticker} />}
              <span className="text-xs text-terminal-text-secondary">{r.securityName}</span>
              <span className="text-xs font-mono text-terminal-text-primary ml-2">{r.fiscalQuarter}</span>
              {r.recommendation && (
                <span className={`text-xs px-2 py-0.5 rounded uppercase ml-2 ${REC_COLORS[r.recommendation] || ""}`}>
                  {r.recommendation}
                </span>
              )}
              <div className="ml-auto flex items-center gap-4 text-xs">
                {r.revenueYoyPct !== null && (
                  <span className={r.revenueYoyPct >= 0 ? "text-terminal-positive" : "text-terminal-negative"}>
                    Rev {formatPercent(r.revenueYoyPct, true)} YoY
                  </span>
                )}
                {r.epsYoyPct !== null && (
                  <span className={r.epsYoyPct >= 0 ? "text-terminal-positive" : "text-terminal-negative"}>
                    EPS {formatPercent(r.epsYoyPct, true)} YoY
                  </span>
                )}
                {r.redFlags && (
                  <span className="text-terminal-negative">! Red flags</span>
                )}
              </div>
            </div>

            {expanded === r.id && (
              <div className="border-t border-terminal-border p-4 space-y-3">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                  <div>
                    <span className="text-terminal-text-secondary">Revenue</span>
                    <p className="font-mono">
                      {r.revenueCents ? formatLargeNumber(r.revenueCents, r.revenueCurrency || "USD") : "-"}
                      {r.revenueYoyPct !== null && (
                        <span className={`ml-1 ${r.revenueYoyPct >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                          ({formatPercent(r.revenueYoyPct, true)})
                        </span>
                      )}
                    </p>
                  </div>
                  <div>
                    <span className="text-terminal-text-secondary">EPS</span>
                    <p className="font-mono">
                      {r.epsCents !== null ? formatCurrency(r.epsCents, r.revenueCurrency || "USD") : "-"}
                      {r.epsYoyPct !== null && (
                        <span className={`ml-1 ${r.epsYoyPct >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                          ({formatPercent(r.epsYoyPct, true)})
                        </span>
                      )}
                    </p>
                  </div>
                  <div>
                    <span className="text-terminal-text-secondary">Gross Margin</span>
                    <p className="font-mono">{r.grossMarginPct !== null ? `${r.grossMarginPct.toFixed(1)}%` : "-"}</p>
                  </div>
                  <div>
                    <span className="text-terminal-text-secondary">Operating Margin</span>
                    <p className="font-mono">{r.operatingMarginPct !== null ? `${r.operatingMarginPct.toFixed(1)}%` : "-"}</p>
                  </div>
                </div>

                {r.forwardGuidance && (
                  <div>
                    <span className="text-xs text-terminal-text-secondary">Forward Guidance</span>
                    <p className="text-sm text-terminal-text-primary mt-1">{r.forwardGuidance}</p>
                  </div>
                )}

                {r.redFlags && (
                  <div>
                    <span className="text-xs text-terminal-negative">Red Flags</span>
                    <p className="text-sm text-terminal-text-primary mt-1">{r.redFlags}</p>
                  </div>
                )}

                {r.recommendationReasoning && (
                  <div>
                    <span className="text-xs text-terminal-text-secondary">Recommendation Reasoning</span>
                    <p className="text-sm text-terminal-text-primary mt-1">{r.recommendationReasoning}</p>
                  </div>
                )}

                <div className="flex gap-4 text-xs text-terminal-text-secondary">
                  {r.reportDate && <span>Report: {formatDate(r.reportDate)}</span>}
                  {r.source && <span>Source: {r.source}</span>}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
