"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGetRaw, apiPost, apiPut, apiDelete } from "@/lib/api";
import { formatCurrency, formatDate, formatPercent } from "@/lib/format";

/* ── Types ── */

interface BondHolding {
  id: number;
  securityId: number;
  ticker: string;
  name: string;
  isin: string | null;
  issuer: string;
  issuerType: string;
  couponRate: number | null;
  couponFrequency: string;
  faceValueCents: number;
  currency: string;
  issueDate: string | null;
  maturityDate: string;
  callDate: string | null;
  purchasePriceCents: number | null;
  purchaseDate: string | null;
  quantity: number;
  yieldToMaturity: number | null;
  currentYield: number | null;
  creditRating: string | null;
  ratingAgency: string | null;
  isInflationLinked: boolean;
  isCallable: boolean;
  daysToMaturity: number;
  yearsToMaturity: number;
  annualIncomeCents: number;
  marketValueCents: number;
  marketPriceCents: number | null;
  notes: string | null;
}

interface BondSummary {
  totalFaceValueCents: number;
  totalMarketValueCents: number;
  weightedAvgYtm: number | null;
  weightedAvgCoupon: number | null;
  totalAnnualIncomeCents: number;
  bondCount: number;
  byIssuerType: Record<string, { count: number; faceValueCents: number; annualIncomeCents: number }>;
  avgCreditRating: string | null;
}

interface LadderBucket {
  label: string;
  count: number;
  totalFaceValueCents: number;
  avgCouponRate: number | null;
  bonds: { ticker: string; issuer: string; maturityDate: string; faceValueCents: number; couponRate: number | null; creditRating: string | null }[];
}

interface IncomeYear {
  year: number;
  annualIncomeCents: number;
  bondsMaturing: number;
  remainingAnnualIncomeCents: number;
  targetAnnualCents: number;
  gapCents: number;
  coveragePct: number;
}

interface GlidepathData {
  currentAge: number;
  currentFixedIncomeCents: number;
  currentFixedIncomePct: number;
  targetFixedIncomePct: number;
  targetFixedIncomeCents: number;
  gapCents: number;
  portfolioTotalCents: number;
  schedule: { age: number; targetFixedIncomePct: number; targetFixedIncomeCents: number; gapCents: number }[];
}

type Tab = "portfolio" | "ladder" | "income" | "glidepath" | "add";

const ISSUER_TYPE_LABELS: Record<string, string> = {
  government: "Government",
  corporate: "Corporate",
  municipal: "Municipal",
  supranational: "Supranational",
};

const RATING_COLORS: Record<string, string> = {
  AAA: "text-terminal-positive",
  AA: "text-terminal-positive",
  "AA+": "text-terminal-positive",
  "AA-": "text-terminal-positive",
  A: "text-terminal-info",
  "A+": "text-terminal-info",
  "A-": "text-terminal-info",
  BBB: "text-terminal-warning",
  "BBB+": "text-terminal-warning",
  "BBB-": "text-terminal-warning",
};

export default function FixedIncomePage() {
  const [tab, setTab] = useState<Tab>("portfolio");

  const tabs: { key: Tab; label: string }[] = [
    { key: "portfolio", label: "Portfolio" },
    { key: "ladder", label: "Maturity Ladder" },
    { key: "income", label: "Income Projection" },
    { key: "glidepath", label: "Glidepath" },
    { key: "add", label: "+ Add Bond" },
  ];

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Fixed Income</h1>

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

      {tab === "portfolio" && <PortfolioTab />}
      {tab === "ladder" && <LadderTab />}
      {tab === "income" && <IncomeTab />}
      {tab === "glidepath" && <GlidepathTab />}
      {tab === "add" && <AddBondTab onCreated={() => setTab("portfolio")} />}
    </div>
  );
}

/* ── Portfolio Tab ── */

function PortfolioTab() {
  const [bonds, setBonds] = useState<BondHolding[]>([]);
  const [summary, setSummary] = useState<BondSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [portfolioRes, summaryRes] = await Promise.all([
          apiGetRaw<{ data: BondHolding[] }>("/fixed-income/portfolio"),
          apiGetRaw<{ data: BondSummary }>("/fixed-income/summary"),
        ]);
        setBonds(portfolioRes.data);
        setSummary(summaryRes.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (!summary || summary.bondCount === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No bonds in portfolio. Add bonds to start tracking fixed income.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Bonds" value={String(summary.bondCount)} />
        <MetricCard label="Total Face Value" value={formatCurrency(summary.totalFaceValueCents)} />
        <MetricCard label="Market Value" value={formatCurrency(summary.totalMarketValueCents)} />
        <MetricCard label="Annual Income" value={formatCurrency(summary.totalAnnualIncomeCents)} color="positive" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Avg YTM"
          value={summary.weightedAvgYtm !== null ? `${summary.weightedAvgYtm}%` : "-"}
        />
        <MetricCard
          label="Avg Coupon"
          value={summary.weightedAvgCoupon !== null ? `${summary.weightedAvgCoupon}%` : "-"}
        />
        <MetricCard
          label="Credit Rating"
          value={summary.avgCreditRating || "-"}
        />
        <MetricCard
          label="Types"
          value={Object.keys(summary.byIssuerType).map(t => ISSUER_TYPE_LABELS[t] || t).join(", ") || "-"}
        />
      </div>

      {/* Bond Holdings Table */}
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
              <th className="text-left p-3">Bond</th>
              <th className="text-left p-3">Issuer</th>
              <th className="text-center p-3">Type</th>
              <th className="text-right p-3">Coupon %</th>
              <th className="text-left p-3">Maturity</th>
              <th className="text-right p-3">Face Value</th>
              <th className="text-right p-3">Market Value</th>
              <th className="text-right p-3">YTM</th>
              <th className="text-center p-3">Rating</th>
              <th className="text-right p-3">Days Left</th>
            </tr>
          </thead>
          <tbody>
            {bonds.map((b) => (
              <tr key={b.id} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
                <td className="p-3">
                  <span className="font-mono text-terminal-accent mr-2">{b.ticker}</span>
                  <span className="text-xs text-terminal-text-secondary">{b.name}</span>
                </td>
                <td className="p-3 text-xs">{b.issuer}</td>
                <td className="text-center p-3 text-xs capitalize">{b.issuerType}</td>
                <td className="text-right p-3 font-mono text-xs">
                  {b.couponRate !== null ? `${b.couponRate}%` : "Zero"}
                </td>
                <td className="p-3 text-xs">{formatDate(b.maturityDate)}</td>
                <td className="text-right p-3 font-mono text-xs">
                  {formatCurrency(Math.round(b.quantity * b.faceValueCents), b.currency)}
                </td>
                <td className="text-right p-3 font-mono text-xs">
                  {formatCurrency(b.marketValueCents, b.currency)}
                </td>
                <td className="text-right p-3 font-mono text-xs">
                  {b.yieldToMaturity !== null ? `${b.yieldToMaturity}%` : "-"}
                </td>
                <td className="text-center p-3">
                  <span className={`text-xs font-mono ${RATING_COLORS[b.creditRating || ""] || "text-terminal-text-secondary"}`}>
                    {b.creditRating || "-"}
                  </span>
                </td>
                <td className={`text-right p-3 font-mono text-xs ${
                  b.daysToMaturity < 365 ? "text-terminal-warning" : ""
                }`}>
                  {b.daysToMaturity}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Maturity Ladder Tab ── */

function LadderTab() {
  const [buckets, setBuckets] = useState<LadderBucket[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: LadderBucket[] }>("/fixed-income/ladder");
        setBuckets(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  const maxFace = Math.max(...buckets.map((b) => b.totalFaceValueCents), 1);
  const hasBonds = buckets.some((b) => b.count > 0);

  if (!hasBonds) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">No bonds to display on the maturity ladder.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Bar Chart */}
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
        <h3 className="text-sm font-medium text-terminal-text-primary mb-4">Maturity Distribution</h3>
        <div className="flex items-end gap-3 h-48">
          {buckets.map((bucket) => {
            const height = bucket.totalFaceValueCents > 0
              ? Math.max((bucket.totalFaceValueCents / maxFace) * 100, 4)
              : 0;
            return (
              <div key={bucket.label} className="flex-1 flex flex-col items-center">
                <span className="text-xs font-mono text-terminal-text-secondary mb-1">
                  {bucket.count > 0 ? formatCurrency(bucket.totalFaceValueCents) : ""}
                </span>
                <div
                  className="w-full rounded-t bg-terminal-accent/60 hover:bg-terminal-accent/80 transition-colors"
                  style={{ height: `${height}%` }}
                  title={`${bucket.count} bond(s), ${formatCurrency(bucket.totalFaceValueCents)}`}
                />
                <span className="text-xs text-terminal-text-secondary mt-2">{bucket.label}</span>
                <span className="text-[10px] text-terminal-text-secondary">{bucket.count} bond{bucket.count !== 1 ? "s" : ""}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Bonds per bucket */}
      {buckets.filter((b) => b.count > 0).map((bucket) => (
        <div key={bucket.label} className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
          <h3 className="text-sm font-medium text-terminal-text-primary mb-2">
            {bucket.label}
            <span className="text-xs text-terminal-text-secondary ml-2">{bucket.count} bond{bucket.count !== 1 ? "s" : ""}</span>
            {bucket.avgCouponRate !== null && (
              <span className="text-xs text-terminal-text-secondary ml-2">Avg coupon: {bucket.avgCouponRate}%</span>
            )}
          </h3>
          <div className="space-y-1">
            {bucket.bonds.map((b, i) => (
              <div key={i} className="flex justify-between text-xs">
                <div>
                  <span className="font-mono text-terminal-accent mr-2">{b.ticker}</span>
                  <span className="text-terminal-text-secondary">{b.issuer}</span>
                </div>
                <div className="flex gap-4">
                  {b.couponRate !== null && <span className="font-mono">{b.couponRate}%</span>}
                  <span className="text-terminal-text-secondary">{formatDate(b.maturityDate)}</span>
                  <span className="font-mono">{formatCurrency(b.faceValueCents)}</span>
                  {b.creditRating && (
                    <span className={RATING_COLORS[b.creditRating] || ""}>{b.creditRating}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Income Projection Tab ── */

function IncomeTab() {
  const [data, setData] = useState<{
    projection: IncomeYear[];
    targetMonthlyCents: number;
    currentAnnualIncomeCents: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: typeof data }>("/fixed-income/income-projection");
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;
  if (!data) return null;

  if (data.projection.length === 0 || data.currentAnnualIncomeCents === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No coupon income to project. Add bonds with coupon rates to see projections.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Current Annual Income" value={formatCurrency(data.currentAnnualIncomeCents)} color="positive" />
        <MetricCard label="Target Monthly" value={formatCurrency(data.targetMonthlyCents)} />
        <MetricCard
          label="Coverage"
          value={data.projection[0] ? `${data.projection[0].coveragePct}%` : "-"}
          color={data.projection[0]?.coveragePct >= 100 ? "positive" : "negative"}
        />
        <MetricCard
          label="Annual Gap"
          value={data.projection[0] ? formatCurrency(data.projection[0].gapCents) : "-"}
          color={data.projection[0]?.gapCents <= 0 ? "positive" : "negative"}
        />
      </div>

      {/* Projection Table */}
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
              <th className="text-left p-3">Year</th>
              <th className="text-right p-3">Coupon Income</th>
              <th className="text-center p-3">Maturing</th>
              <th className="text-right p-3">Remaining Income</th>
              <th className="text-right p-3">Target</th>
              <th className="text-right p-3">Gap</th>
              <th className="p-3 w-32">Coverage</th>
            </tr>
          </thead>
          <tbody>
            {data.projection.map((yr) => (
              <tr key={yr.year} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
                <td className="p-3 font-mono text-xs">{yr.year}</td>
                <td className="text-right p-3 font-mono text-xs">{formatCurrency(yr.annualIncomeCents)}</td>
                <td className="text-center p-3 text-xs">
                  {yr.bondsMaturing > 0 && (
                    <span className="text-terminal-warning">{yr.bondsMaturing}</span>
                  )}
                </td>
                <td className="text-right p-3 font-mono text-xs">{formatCurrency(yr.remainingAnnualIncomeCents)}</td>
                <td className="text-right p-3 font-mono text-xs text-terminal-text-secondary">
                  {formatCurrency(yr.targetAnnualCents)}
                </td>
                <td className={`text-right p-3 font-mono text-xs ${
                  yr.gapCents <= 0 ? "text-terminal-positive" : "text-terminal-negative"
                }`}>
                  {yr.gapCents <= 0 ? "Covered" : formatCurrency(yr.gapCents)}
                </td>
                <td className="p-3">
                  <div className="relative h-3 bg-terminal-bg-tertiary rounded overflow-hidden">
                    <div
                      className={`h-full rounded ${yr.coveragePct >= 100 ? "bg-terminal-positive/60" : "bg-terminal-accent/60"}`}
                      style={{ width: `${Math.min(yr.coveragePct, 100)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-terminal-text-secondary">{yr.coveragePct}%</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Glidepath Tab ── */

function GlidepathTab() {
  const [data, setData] = useState<GlidepathData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: GlidepathData }>("/fixed-income/glidepath");
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;
  if (!data) return null;

  const driftPct = data.currentFixedIncomePct - data.targetFixedIncomePct;

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Current FI %" value={`${data.currentFixedIncomePct}%`} />
        <MetricCard label="Target FI %" value={`${data.targetFixedIncomePct}%`} />
        <MetricCard
          label="Drift"
          value={formatPercent(driftPct, true)}
          color={Math.abs(driftPct) <= 3 ? "positive" : "negative"}
        />
        <MetricCard
          label="Gap to Target"
          value={data.gapCents > 0 ? formatCurrency(data.gapCents) : "On track"}
          color={data.gapCents <= 0 ? "positive" : "negative"}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <MetricCard label="FI Holdings" value={formatCurrency(data.currentFixedIncomeCents)} />
        <MetricCard label="Portfolio Total" value={formatCurrency(data.portfolioTotalCents)} />
      </div>

      {/* Glidepath Schedule */}
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
        <h3 className="text-sm font-medium text-terminal-text-primary mb-4">Fixed Income Glidepath Schedule</h3>
        <div className="space-y-4">
          {data.schedule.map((s) => {
            const isCurrent = s.age === data.currentAge;
            return (
              <div key={s.age} className={`${isCurrent ? "bg-terminal-bg-tertiary p-3 rounded" : ""}`}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-mono font-medium ${isCurrent ? "text-terminal-accent" : "text-terminal-text-primary"}`}>
                      Age {s.age}
                    </span>
                    {isCurrent && (
                      <span className="text-xs px-2 py-0.5 rounded bg-terminal-accent/20 text-terminal-accent">Current</span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-xs">
                    <span className="text-terminal-text-secondary">Target: {s.targetFixedIncomePct}%</span>
                    <span className="font-mono">{formatCurrency(s.targetFixedIncomeCents)}</span>
                    {s.gapCents > 0 && (
                      <span className="text-terminal-warning font-mono">Gap: {formatCurrency(s.gapCents)}</span>
                    )}
                  </div>
                </div>
                <div className="relative h-4 bg-terminal-bg-primary rounded overflow-hidden">
                  <div
                    className="absolute h-full bg-terminal-accent/30 rounded"
                    style={{ width: `${s.targetFixedIncomePct}%` }}
                  />
                  {isCurrent && (
                    <div
                      className="absolute h-full bg-terminal-accent rounded"
                      style={{ width: `${data.currentFixedIncomePct}%` }}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ── Add Bond Tab ── */

function AddBondTab({ onCreated }: { onCreated: () => void }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const [ticker, setTicker] = useState("");
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [isin, setIsin] = useState("");
  const [issuer, setIssuer] = useState("");
  const [issuerType, setIssuerType] = useState("government");
  const [couponRate, setCouponRate] = useState("");
  const [couponFrequency, setCouponFrequency] = useState("annual");
  const [faceValue, setFaceValue] = useState("");
  const [maturityDate, setMaturityDate] = useState("");
  const [purchasePrice, setPurchasePrice] = useState("");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [creditRating, setCreditRating] = useState("");
  const [ratingAgency, setRatingAgency] = useState("");
  const [isInflationLinked, setIsInflationLinked] = useState(false);
  const [notes, setNotes] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ticker || !name || !issuer || !faceValue || !maturityDate) {
      setError("Ticker, name, issuer, face value, and maturity date are required.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await apiPost("/fixed-income/bonds", {
        ticker,
        name,
        currency,
        isin: isin || undefined,
        issuer,
        issuer_type: issuerType,
        coupon_rate: couponRate ? parseFloat(couponRate) / 100 : undefined,
        coupon_frequency: couponFrequency,
        face_value_cents: Math.round(parseFloat(faceValue) * 100),
        maturity_date: maturityDate,
        purchase_price_cents: purchasePrice ? Math.round(parseFloat(purchasePrice) * 100) : undefined,
        purchase_date: purchaseDate || undefined,
        quantity: parseFloat(quantity) || 1,
        credit_rating: creditRating || undefined,
        rating_agency: ratingAgency || undefined,
        is_inflation_linked: isInflationLinked,
        notes: notes || undefined,
      });
      onCreated();
    } catch {
      setError("Failed to create bond.");
    }
    setSubmitting(false);
  };

  const inputCls = "w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary focus:border-terminal-accent focus:outline-none";
  const labelCls = "block text-xs text-terminal-text-secondary mb-1";

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl space-y-4">
      {error && <div className="text-sm text-terminal-negative bg-terminal-negative/10 px-3 py-2 rounded">{error}</div>}

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className={labelCls}>Ticker *</label>
          <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="e.g. FI-GOV-2030" className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Name *</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Finland Govt 2.5% 2030" className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>ISIN</label>
          <input value={isin} onChange={(e) => setIsin(e.target.value)} placeholder="FI0002..." className={inputCls} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className={labelCls}>Issuer *</label>
          <input value={issuer} onChange={(e) => setIssuer(e.target.value)} placeholder="Republic of Finland" className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Issuer Type</label>
          <select value={issuerType} onChange={(e) => setIssuerType(e.target.value)} className={inputCls}>
            <option value="government">Government</option>
            <option value="corporate">Corporate</option>
            <option value="municipal">Municipal</option>
            <option value="supranational">Supranational</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Currency</label>
          <select value={currency} onChange={(e) => setCurrency(e.target.value)} className={inputCls}>
            <option value="EUR">EUR</option>
            <option value="USD">USD</option>
            <option value="SEK">SEK</option>
            <option value="GBP">GBP</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className={labelCls}>Coupon Rate %</label>
          <input type="number" step="0.01" value={couponRate} onChange={(e) => setCouponRate(e.target.value)} placeholder="2.50" className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Coupon Frequency</label>
          <select value={couponFrequency} onChange={(e) => setCouponFrequency(e.target.value)} className={inputCls}>
            <option value="annual">Annual</option>
            <option value="semi_annual">Semi-Annual</option>
            <option value="quarterly">Quarterly</option>
            <option value="zero_coupon">Zero Coupon</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Face Value *</label>
          <input type="number" step="0.01" value={faceValue} onChange={(e) => setFaceValue(e.target.value)} placeholder="1000.00" className={inputCls} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className={labelCls}>Maturity Date *</label>
          <input type="date" value={maturityDate} onChange={(e) => setMaturityDate(e.target.value)} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Purchase Price</label>
          <input type="number" step="0.01" value={purchasePrice} onChange={(e) => setPurchasePrice(e.target.value)} placeholder="995.00" className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Purchase Date</label>
          <input type="date" value={purchaseDate} onChange={(e) => setPurchaseDate(e.target.value)} className={inputCls} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className={labelCls}>Quantity</label>
          <input type="number" step="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Credit Rating</label>
          <input value={creditRating} onChange={(e) => setCreditRating(e.target.value)} placeholder="AA+" className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Rating Agency</label>
          <input value={ratingAgency} onChange={(e) => setRatingAgency(e.target.value)} placeholder="S&P" className={inputCls} />
        </div>
      </div>

      <div className="flex gap-4">
        <label className="flex items-center gap-1.5 text-sm text-terminal-text-secondary">
          <input type="checkbox" checked={isInflationLinked} onChange={(e) => setIsInflationLinked(e.target.checked)} className="accent-terminal-accent" />
          Inflation-linked
        </label>
      </div>

      <div>
        <label className={labelCls}>Notes</label>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="Additional notes" className={inputCls} />
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="px-6 py-2 bg-terminal-accent text-terminal-bg-primary rounded font-medium text-sm hover:opacity-90 disabled:opacity-50"
      >
        {submitting ? "Adding..." : "Add Bond"}
      </button>
    </form>
  );
}

/* ── Shared MetricCard ── */

function MetricCard({ label, value, color }: { label: string; value: string; color?: "positive" | "negative" }) {
  const colorClass = color === "positive"
    ? "text-terminal-positive"
    : color === "negative"
      ? "text-terminal-negative"
      : "text-terminal-text-primary";

  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
      <p className="text-xs text-terminal-text-secondary mb-1">{label}</p>
      <p className={`text-2xl font-mono font-bold ${colorClass}`}>{value}</p>
    </div>
  );
}
