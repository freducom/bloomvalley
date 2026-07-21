"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { PeriodPicker, PeriodRange, presetToRange } from "@/components/ui/PeriodPicker";
import { InfoTip } from "@/components/ui/InfoTip";
import { TickerLink } from "@/components/ui/TickerLink";
import { Private } from "@/lib/privacy";
import { formatCurrency, formatPercent } from "@/lib/format";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

interface Totals {
  realizedGainCents: number;
  realizedLossCents: number;
  dividendCents: number;
  unrealizedGainCents: number;
  unrealizedLossCents: number;
  netCents: number;
}

interface SecurityRow {
  securityId: number;
  ticker: string;
  name: string;
  assetClass: string;
  sector: string | null;
  realizedCents: number;
  dividendCents: number;
  unrealizedChangeCents: number;
  netCents: number;
  sharesEnd: string;
  sharesStart: string;
  priceStartCents: number | null;
  priceEndCents: number | null;
  valueEndEurCents: number;
  valueStartEurCents: number;
  costOfBuysInPeriodEurCents: number;
  baselineEurCents: number;
  returnPct: number | null;
}

interface Payload {
  period: { from: string; to: string };
  currency: string;
  totals: Totals;
  bySecurity: SecurityRow[];
}

type SortKey = "netCents" | "realizedCents" | "dividendCents" | "unrealizedChangeCents" | "returnPct" | "ticker";

const BUCKET_INFO: Record<string, string> = {
  realized:
    "Sum of realized gains and losses from tax lots closed inside the period. Uses specific-identification cost basis (FIFO match) already stored on each lot in EUR cents.",
  dividend:
    "Net dividends (after withholding tax) with pay_date inside the period. Reads dividends.net_amount_eur_cents.",
  unrealizedGain:
    "Price movement during the period on shares still held at period end. Split into two parts: shares held throughout the period contribute shares × (price_end − price_start); shares bought during the period and still held contribute shares × (price_end − avg_buy_price_in_period). Fully-closed positions contribute 0. Note: this is the change during the window only — not the full gap from your cost basis (see the portfolio page for that). Only securities where this is positive contribute here.",
  unrealizedLoss:
    "Same math as Unrealized gains, but only securities where the period-attributed price change is negative.",
  net:
    "Sum of realized + dividends + unrealized change. This is the total portfolio P&L for the period, isolated from cash injected or withdrawn.",
};

function ColoredAmount({ cents }: { cents: number }) {
  const pos = cents > 0;
  const neg = cents < 0;
  const cls = pos ? "text-terminal-positive" : neg ? "text-terminal-negative" : "text-terminal-text-secondary";
  const sign = pos ? "+" : "";
  return <span className={cls}><Private>{sign}{formatCurrency(cents, "EUR")}</Private></span>;
}

function StatCard({
  label,
  cents,
  info,
  emphasized,
}: {
  label: string;
  cents: number;
  info: string;
  emphasized?: boolean;
}) {
  const border = emphasized ? "border-terminal-accent/50" : "border-terminal-border";
  return (
    <div className={`bg-terminal-bg-secondary border ${border} rounded p-3`}>
      <div className="text-xs text-terminal-text-muted flex items-center gap-1 mb-1">
        {label}
        <InfoTip text={info} />
      </div>
      <div className="text-xl font-bold">
        <ColoredAmount cents={cents} />
      </div>
    </div>
  );
}

export default function PerformancePage() {
  const [range, setRange] = useState<PeriodRange>(() => presetToRange("YTD"));
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("netCents");
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const url = `${API_BASE}/api/v1/performance?fromDate=${range.from}&toDate=${range.to}`;
        const res = await fetch(url, { cache: "no-store" });
        const json = await res.json().catch(() => null);
        if (!res.ok) {
          const detail = json?.detail;
          throw new Error(typeof detail === "string" ? detail : detail?.message || `API error: ${res.status}`);
        }
        if (!cancelled) setData((json.data as Payload) || null);
      } catch (e: unknown) {
        if (!cancelled) setError(String((e as Error)?.message ?? e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [range.from, range.to]);

  const sortedRows = useMemo(() => {
    if (!data?.bySecurity) return [];
    const rows = [...data.bySecurity];
    rows.sort((a, b) => {
      const av = sortKey === "ticker" ? a.ticker : (a as unknown as Record<string, number>)[sortKey];
      const bv = sortKey === "ticker" ? b.ticker : (b as unknown as Record<string, number>)[sortKey];
      let diff: number;
      if (typeof av === "string" && typeof bv === "string") {
        diff = av.localeCompare(bv);
      } else {
        diff = ((av as number) || 0) - ((bv as number) || 0);
      }
      return sortAsc ? diff : -diff;
    });
    return rows;
  }, [data, sortKey, sortAsc]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setSortAsc((v) => !v);
    else { setSortKey(key); setSortAsc(false); }
  };

  const totals = data?.totals;

  return (
    <div className="p-6 max-w-7xl">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h1 className="text-lg font-bold text-terminal-text-primary flex items-center gap-2">
            Performance
            <InfoTip text="Portfolio P&L for a chosen period, split into realized (from closed tax lots), dividends (paid in period), and unrealized (period-attributed price change on positions still held). All values in EUR. Cash deposits and withdrawals are excluded — this measures investment returns, not portfolio balance changes." />
          </h1>
          <p className="text-xs text-terminal-text-muted mt-1">
            {data?.period.from} → {data?.period.to} — investment returns broken down by source.
          </p>
        </div>
        <PeriodPicker value={range} onChange={setRange} />
      </div>

      {loading && (
        <div className="text-sm text-terminal-text-muted animate-pulse py-8">Loading performance…</div>
      )}
      {error && !loading && (
        <div className="bg-terminal-negative/10 border border-terminal-negative/40 text-terminal-negative text-sm rounded p-4">
          <div className="font-semibold mb-1">Unable to load performance</div>
          <div className="text-xs">{error}</div>
        </div>
      )}

      {!loading && !error && totals && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
            <StatCard label="Realized gains"   cents={totals.realizedGainCents}   info={BUCKET_INFO.realized} />
            <StatCard label="Realized losses"  cents={totals.realizedLossCents}   info={BUCKET_INFO.realized} />
            <StatCard label="Dividends"        cents={totals.dividendCents}       info={BUCKET_INFO.dividend} />
            <StatCard label="Unrealized gains" cents={totals.unrealizedGainCents} info={BUCKET_INFO.unrealizedGain} />
            <StatCard label="Unrealized losses" cents={totals.unrealizedLossCents} info={BUCKET_INFO.unrealizedLoss} />
            <StatCard label="Net P&L"          cents={totals.netCents}            info={BUCKET_INFO.net} emphasized />
          </div>

          {sortedRows.length === 0 ? (
            <div className="text-sm text-terminal-text-muted bg-terminal-bg-secondary border border-terminal-border rounded p-4">
              No P&L activity in this period.
            </div>
          ) : (
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded overflow-hidden">
              <div className="px-3 py-2 border-b border-terminal-border flex items-center justify-between">
                <div className="text-sm font-semibold text-terminal-text-primary">
                  Per-security ({sortedRows.length})
                </div>
                <div className="text-xs text-terminal-text-muted">Click a column to sort</div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-terminal-bg-tertiary text-terminal-text-secondary">
                    <tr>
                      <th className="text-left p-2 cursor-pointer hover:text-terminal-text-primary" onClick={() => toggleSort("ticker")}>Ticker</th>
                      <th className="text-left p-2">Name</th>
                      <th className="text-left p-2">Sector</th>
                      <th className="text-right p-2 cursor-pointer hover:text-terminal-text-primary" onClick={() => toggleSort("realizedCents")}>Realized</th>
                      <th className="text-right p-2 cursor-pointer hover:text-terminal-text-primary" onClick={() => toggleSort("dividendCents")}>Dividends</th>
                      <th className="text-right p-2 cursor-pointer hover:text-terminal-text-primary" onClick={() => toggleSort("unrealizedChangeCents")}>Unrealized Δ</th>
                      <th className="text-right p-2 cursor-pointer hover:text-terminal-text-primary" onClick={() => toggleSort("netCents")}>Net</th>
                      <th className="text-right p-2 cursor-pointer hover:text-terminal-text-primary" onClick={() => toggleSort("returnPct")}>
                        <span className="inline-flex items-center gap-1">
                          Return
                          <InfoTip text="Net P&L ÷ capital-at-risk baseline. Baseline = |value at period start| + EUR spent on buys during the period. Sells are not subtracted from the baseline (returned capital + P&L is already in the numerator). Shows '—' when no capital was deployed to this position in the window (e.g. security had no starting position AND no new buys)." />
                        </span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRows.map((r) => (
                      <tr key={r.securityId} className="border-b border-terminal-border/60 hover:bg-terminal-bg-hover/30">
                        <td className="p-2"><TickerLink ticker={r.ticker} /></td>
                        <td className="p-2 text-terminal-text-secondary truncate max-w-xs">{r.name}</td>
                        <td className="p-2 text-terminal-text-muted">{r.sector || "—"}</td>
                        <td className="p-2 text-right"><ColoredAmount cents={r.realizedCents} /></td>
                        <td className="p-2 text-right"><ColoredAmount cents={r.dividendCents} /></td>
                        <td className="p-2 text-right"><ColoredAmount cents={r.unrealizedChangeCents} /></td>
                        <td className="p-2 text-right font-semibold"><ColoredAmount cents={r.netCents} /></td>
                        <td className="p-2 text-right text-terminal-text-secondary">
                          {r.returnPct !== null ? formatPercent(r.returnPct * 100, true) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="mt-3 text-xs text-terminal-text-muted">
            <Link href="/tax" className="text-terminal-accent hover:underline">Tax page →</Link> for Finnish capital-gains calculations.
            <span className="ml-3">Cash deposits, withdrawals, fees and interest are excluded from this view.</span>
          </div>
        </>
      )}
    </div>
  );
}
