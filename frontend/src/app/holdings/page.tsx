"use client";

import { useEffect, useState, useCallback } from "react";
import { apiGet, apiGetRaw, apiPost } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { Private } from "@/lib/privacy";
import { TickerLink } from "@/components/ui/TickerLink";

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

interface SoldHolding {
  accountId: number;
  accountName: string | null;
  securityId: number;
  ticker: string;
  name: string;
  assetClass: string;
  totalBought: string;
  totalSold: string;
  totalCostCents: number;
  totalProceedsCents: number;
  totalFeesCents: number;
  realizedPnlCents: number;
  currency: string;
  firstBuyDate: string | null;
  lastSellDate: string | null;
}

interface DividendByHolding {
  securityId: number;
  ticker: string;
  annualIncomeCents: number;
}

interface LiveQuote {
  securityId: number;
  ticker: string;
  current: number;
  change: number;
  changePercent: number;
}

type SortKey = "ticker" | "name" | "accountName" | "assetClass" | "quantity" | "avgCostCents" | "currentPriceCents" | "marketValueEurCents" | "unrealizedPnlCents" | "unrealizedPnlPct" | "upcomingDivCents" | "liveChange";
type SoldSortKey = "ticker" | "name" | "accountName" | "assetClass" | "totalCostCents" | "totalProceedsCents" | "realizedPnlCents" | "lastSellDate";

interface SellModalProps {
  holding: Holding;
  onClose: () => void;
  onSuccess: () => void;
}

function SellModal({ holding, onClose, onSuccess }: SellModalProps) {
  const [quantity, setQuantity] = useState(holding.quantity);
  const [pricePerUnit, setPricePerUnit] = useState(
    holding.currentPriceCents != null ? (holding.currentPriceCents / 100).toFixed(2) : ""
  );
  const [fee, setFee] = useState("0");
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().split("T")[0]);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const qty = parseFloat(quantity) || 0;
  const price = parseFloat(pricePerUnit) || 0;
  const totalProceeds = Math.round(qty * price * 100);
  const feeCents = Math.round((parseFloat(fee) || 0) * 100);
  const netProceeds = totalProceeds - feeCents;

  const handleSubmit = async () => {
    setError(null);
    if (qty <= 0) { setError("Quantity must be positive"); return; }
    if (price <= 0) { setError("Price must be positive"); return; }
    setSubmitting(true);
    try {
      await apiPost("/portfolio/sell", {
        account_id: holding.accountId,
        security_id: holding.securityId,
        quantity: quantity,
        price_cents: Math.round(price * 100),
        total_cents: totalProceeds,
        fee_cents: feeCents,
        currency: holding.currency,
        trade_date: tradeDate,
        notes: notes || null,
      });
      onSuccess();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to sell";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-terminal-bg-primary border border-terminal-border rounded-lg p-6 w-full max-w-md shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-bold mb-1">Sell {holding.ticker}</h2>
        <p className="text-sm text-terminal-text-secondary mb-4">{holding.name} &middot; {holding.accountName}</p>

        {error && (
          <div className="bg-terminal-negative/20 text-terminal-negative text-sm px-3 py-2 rounded mb-3">{error}</div>
        )}

        <div className="space-y-3">
          <div>
            <label className="block text-xs text-terminal-text-secondary mb-1">
              Quantity (max {parseFloat(holding.quantity).toLocaleString("en-US", { maximumFractionDigits: 4 })})
            </label>
            <input
              type="number"
              step="any"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="w-full bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-2 font-mono text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-terminal-text-secondary mb-1">Price per unit ({holding.currency})</label>
            <input
              type="number"
              step="any"
              value={pricePerUnit}
              onChange={(e) => setPricePerUnit(e.target.value)}
              className="w-full bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-2 font-mono text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-terminal-text-secondary mb-1">Fee ({holding.currency})</label>
            <input
              type="number"
              step="any"
              value={fee}
              onChange={(e) => setFee(e.target.value)}
              className="w-full bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-2 font-mono text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-terminal-text-secondary mb-1">Trade date</label>
            <input
              type="date"
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
              className="w-full bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-2 font-mono text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-terminal-text-secondary mb-1">Notes (optional)</label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-2 text-sm"
              placeholder="Reason for selling..."
            />
          </div>

          <div className="border-t border-terminal-border pt-3 space-y-1 text-sm font-mono">
            <div className="flex justify-between">
              <span className="text-terminal-text-secondary">Gross proceeds</span>
              <Private><span>{formatCurrency(totalProceeds, holding.currency)}</span></Private>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-text-secondary">Fees</span>
              <span className="text-terminal-negative">-{formatCurrency(feeCents, holding.currency)}</span>
            </div>
            <div className="flex justify-between font-bold">
              <span>Net to cash</span>
              <Private><span className="text-terminal-positive">{formatCurrency(netProceeds, holding.currency)}</span></Private>
            </div>
          </div>
        </div>

        <div className="flex gap-3 mt-5">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 border border-terminal-border rounded text-sm hover:bg-terminal-bg-secondary transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || qty <= 0 || price <= 0}
            className="flex-1 px-4 py-2 bg-terminal-negative/20 text-terminal-negative border border-terminal-negative/40 rounded text-sm font-medium hover:bg-terminal-negative/30 transition-colors disabled:opacity-50"
          >
            {submitting ? "Selling..." : "Confirm Sell"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function HoldingsPage() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [soldHoldings, setSoldHoldings] = useState<SoldHolding[]>([]);
  const [divMap, setDivMap] = useState<Record<number, number>>({}); // securityId -> 6-month income cents
  const [quoteMap, setQuoteMap] = useState<Record<number, LiveQuote>>({});
  const [quotesLoading, setQuotesLoading] = useState(false);
  const [quotesTime, setQuotesTime] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("marketValueEurCents");
  const [sortAsc, setSortAsc] = useState(false);
  const [soldSortKey, setSoldSortKey] = useState<SoldSortKey>("lastSellDate");
  const [soldSortAsc, setSoldSortAsc] = useState(false);
  const [filterAccount, setFilterAccount] = useState<string>("all");
  const [tab, setTab] = useState<"current" | "sold">("current");
  const [sellTarget, setSellTarget] = useState<Holding | null>(null);

  const fetchQuotes = useCallback(async () => {
    setQuotesLoading(true);
    try {
      const res = await apiGetRaw<{ data: LiveQuote[]; meta: { timestamp: string } }>("/quotes/live");
      const qm: Record<number, LiveQuote> = {};
      for (const q of res.data) qm[q.securityId] = q;
      setQuoteMap(qm);
      setQuotesTime(new Date(res.meta.timestamp).toLocaleTimeString("fi-FI", { hour: "2-digit", minute: "2-digit" }));
    } catch { /* */ }
    finally { setQuotesLoading(false); }
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [holdingsData, divData, soldData] = await Promise.all([
        apiGet<Holding[]>("/portfolio/holdings"),
        apiGetRaw<{ data: { byHolding: DividendByHolding[] } }>("/dividends/income-projection")
          .catch(() => ({ data: { byHolding: [] } })),
        apiGet<SoldHolding[]>("/portfolio/sold-holdings"),
      ]);
      setHoldings(holdingsData);
      setSoldHoldings(soldData);
      const dm: Record<number, number> = {};
      for (const d of divData.data.byHolding || []) {
        dm[d.securityId] = Math.round(d.annualIncomeCents / 2);
      }
      setDivMap(dm);
    } catch (e) {
      console.error("Failed to load holdings:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchQuotes();
    const interval = setInterval(fetchQuotes, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchData, fetchQuotes]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const handleSoldSort = (key: SoldSortKey) => {
    if (soldSortKey === key) setSoldSortAsc(!soldSortAsc);
    else { setSoldSortKey(key); setSoldSortAsc(false); }
  };

  const arrow = (key: SortKey) => sortKey === key ? (sortAsc ? " ▲" : " ▼") : "";
  const soldArrow = (key: SoldSortKey) => soldSortKey === key ? (soldSortAsc ? " ▲" : " ▼") : "";

  const accounts = Array.from(new Set(holdings.map((h) => h.accountName)));

  const filtered = filterAccount === "all" ? holdings : holdings.filter((h) => h.accountName === filterAccount);

  const sorted = [...filtered].sort((a, b) => {
    let av: number | string = 0;
    let bv: number | string = 0;
    if (sortKey === "ticker" || sortKey === "name" || sortKey === "accountName" || sortKey === "assetClass") {
      av = (a[sortKey] || "").toLowerCase();
      bv = (b[sortKey] || "").toLowerCase();
      return sortAsc ? (av as string).localeCompare(bv as string) : (bv as string).localeCompare(av as string);
    }
    if (sortKey === "quantity") { av = parseFloat(a.quantity) || 0; bv = parseFloat(b.quantity) || 0; }
    else if (sortKey === "upcomingDivCents") { av = divMap[a.securityId] ?? 0; bv = divMap[b.securityId] ?? 0; }
    else if (sortKey === "liveChange") { av = quoteMap[a.securityId]?.changePercent ?? -Infinity; bv = quoteMap[b.securityId]?.changePercent ?? -Infinity; }
    else { av = (a[sortKey] ?? -Infinity) as number; bv = (b[sortKey] ?? -Infinity) as number; }
    return sortAsc ? av - bv : bv - av;
  });

  const sortedSold = [...soldHoldings].sort((a, b) => {
    if (soldSortKey === "ticker" || soldSortKey === "name" || soldSortKey === "accountName" || soldSortKey === "assetClass") {
      const av = ((a as Record<string, unknown>)[soldSortKey] as string || "").toLowerCase();
      const bv = ((b as Record<string, unknown>)[soldSortKey] as string || "").toLowerCase();
      return soldSortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    if (soldSortKey === "lastSellDate") {
      const av = a.lastSellDate || "";
      const bv = b.lastSellDate || "";
      return soldSortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    const av = (a[soldSortKey] ?? -Infinity) as number;
    const bv = (b[soldSortKey] ?? -Infinity) as number;
    return soldSortAsc ? av - bv : bv - av;
  });

  // Summary
  const totalValue = filtered.reduce((s, h) => s + (h.marketValueEurCents ?? 0), 0);
  const totalCost = filtered.reduce((s, h) => s + (h.costBasisEurCents ?? 0), 0);
  const totalPnl = totalValue - totalCost;
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
  const totalDiv6m = filtered.reduce((s, h) => s + (divMap[h.securityId] ?? 0), 0);

  if (loading) {
    return (
      <div className="animate-pulse">
        <div className="h-8 bg-terminal-bg-secondary rounded w-48 mb-6" />
        <div className="h-64 bg-terminal-bg-secondary rounded" />
      </div>
    );
  }

  const TH = ({ k, align, children }: { k: SortKey; align?: string; children: React.ReactNode }) => (
    <th
      className={`${align || "text-right"} px-4 py-2 font-medium cursor-pointer select-none hover:text-terminal-accent transition-colors whitespace-nowrap`}
      onClick={() => handleSort(k)}
    >
      {children}{arrow(k)}
    </th>
  );

  const SoldTH = ({ k, align, children }: { k: SoldSortKey; align?: string; children: React.ReactNode }) => (
    <th
      className={`${align || "text-right"} px-4 py-2 font-medium cursor-pointer select-none hover:text-terminal-accent transition-colors whitespace-nowrap`}
      onClick={() => handleSoldSort(k)}
    >
      {children}{soldArrow(k)}
    </th>
  );

  return (
    <div>
      {sellTarget && (
        <SellModal
          holding={sellTarget}
          onClose={() => setSellTarget(null)}
          onSuccess={() => {
            setSellTarget(null);
            setLoading(true);
            fetchData();
          }}
        />
      )}

      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h1 className="text-3xl font-bold">Holdings</h1>
          <div className="flex rounded-md border border-terminal-border overflow-hidden text-sm">
            <button
              onClick={() => setTab("current")}
              className={`px-3 py-1 transition-colors ${tab === "current" ? "bg-terminal-accent/20 text-terminal-accent" : "text-terminal-text-secondary hover:text-terminal-text-primary"}`}
            >
              Current ({holdings.length})
            </button>
            <button
              onClick={() => setTab("sold")}
              className={`px-3 py-1 transition-colors border-l border-terminal-border ${tab === "sold" ? "bg-terminal-negative/20 text-terminal-negative" : "text-terminal-text-secondary hover:text-terminal-text-primary"}`}
            >
              Sold ({soldHoldings.length})
            </button>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {tab === "current" && (
            <>
              {/* Account filter */}
              <select
                value={filterAccount}
                onChange={(e) => setFilterAccount(e.target.value)}
                className="bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-1 text-sm font-mono text-terminal-text-primary"
              >
                <option value="all">All accounts</option>
                {accounts.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
              {/* Summary */}
              <div className="text-sm font-mono text-terminal-text-secondary">
                <Private>{formatCurrency(totalValue)}</Private>
                <span className={`ml-2 ${totalPnl >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                  <Private>{formatCurrency(totalPnl)}</Private> (<Private>{formatPercent(totalPnlPct, true)}</Private>)
                </span>
                {totalDiv6m > 0 && (
                  <span className="ml-3 text-terminal-positive">
                    Div 6M: <Private>{formatCurrency(totalDiv6m)}</Private>
                  </span>
                )}
                {quotesTime && (
                  <span className="ml-3 text-terminal-text-tertiary text-xs">
                    Live {quotesTime}{quotesLoading ? " ..." : ""}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {tab === "current" ? (
        <div className="border border-terminal-border rounded-md overflow-hidden max-h-[80vh] overflow-y-auto overflow-x-auto">
          <table className="w-full min-w-[800px]">
            <thead className="sticky top-0 z-10 bg-terminal-bg-secondary">
              <tr className="text-terminal-text-secondary text-sm">
                <TH k="ticker" align="text-left">Ticker</TH>
                <TH k="name" align="text-left">Name</TH>
                <TH k="accountName" align="text-left">Account</TH>
                <TH k="assetClass" align="text-left">Class</TH>
                <TH k="quantity">Qty</TH>
                <TH k="avgCostCents">Avg Cost</TH>
                <TH k="currentPriceCents">Close</TH>
                <TH k="liveChange">Live</TH>
                <TH k="marketValueEurCents">Market Value</TH>
                <TH k="unrealizedPnlCents">P&L</TH>
                <TH k="unrealizedPnlPct">P&L %</TH>
                <TH k="upcomingDivCents">Div 6M</TH>
                <th className="px-4 py-2 text-right font-medium whitespace-nowrap"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((h) => {
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
                    <td className="px-4 py-2 font-mono text-sm">
                      <TickerLink ticker={h.ticker} />
                    </td>
                    <td className="px-4 py-2 text-sm">{h.name}</td>
                    <td className="px-4 py-2 text-xs text-terminal-text-secondary">{h.accountName}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded font-mono ${
                        h.assetClass === "stock" ? "bg-terminal-info/20 text-terminal-info"
                          : h.assetClass === "etf" ? "bg-terminal-accent/20 text-terminal-accent"
                          : h.assetClass === "crypto" ? "bg-terminal-warning/20 text-terminal-warning"
                          : "bg-terminal-bg-tertiary text-terminal-text-tertiary"
                      }`}>
                        {h.assetClass}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      <Private>{parseFloat(h.quantity).toLocaleString("en-US", { maximumFractionDigits: 4 })}</Private>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      <Private>{formatCurrency(h.avgCostCents, h.currency)}</Private>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {h.currentPriceCents != null
                        ? formatCurrency(h.currentPriceCents, h.priceCurrency)
                        : <span className="text-terminal-text-tertiary">--</span>}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {quoteMap[h.securityId] ? (
                        <div>
                          <span className="text-terminal-text-primary">{quoteMap[h.securityId].current.toFixed(2)}</span>
                          <span className={`ml-1 text-xs ${quoteMap[h.securityId].changePercent >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                            {quoteMap[h.securityId].changePercent >= 0 ? "+" : ""}{quoteMap[h.securityId].changePercent.toFixed(2)}%
                          </span>
                        </div>
                      ) : (
                        <span className="text-terminal-text-tertiary">--</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      <Private>{h.marketValueEurCents != null ? formatCurrency(h.marketValueEurCents) : "--"}</Private>
                    </td>
                    <td className={`px-4 py-2 text-right font-mono text-sm ${pnlColor}`}>
                      <Private>{h.unrealizedPnlCents != null ? formatCurrency(h.unrealizedPnlCents) : "--"}</Private>
                    </td>
                    <td className={`px-4 py-2 text-right font-mono text-sm ${pnlColor}`}>
                      <Private>{h.unrealizedPnlPct != null ? formatPercent(h.unrealizedPnlPct, true) : "--"}</Private>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {divMap[h.securityId] ? (
                        <Private>
                          <span className="text-terminal-positive">{formatCurrency(divMap[h.securityId])}</span>
                        </Private>
                      ) : (
                        <span className="text-terminal-text-tertiary">--</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => setSellTarget(h)}
                        className="text-xs px-2 py-1 rounded border border-terminal-negative/40 text-terminal-negative hover:bg-terminal-negative/20 transition-colors"
                      >
                        Sell
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="border border-terminal-border rounded-md overflow-hidden max-h-[80vh] overflow-y-auto overflow-x-auto">
          {soldHoldings.length === 0 ? (
            <div className="p-8 text-center text-terminal-text-secondary">No sold holdings yet.</div>
          ) : (
            <table className="w-full min-w-[700px]">
              <thead className="sticky top-0 z-10 bg-terminal-bg-secondary">
                <tr className="text-terminal-text-secondary text-sm">
                  <SoldTH k="ticker" align="text-left">Ticker</SoldTH>
                  <SoldTH k="name" align="text-left">Name</SoldTH>
                  <SoldTH k="accountName" align="text-left">Account</SoldTH>
                  <SoldTH k="assetClass" align="text-left">Class</SoldTH>
                  <SoldTH k="totalCostCents">Cost Basis</SoldTH>
                  <SoldTH k="totalProceedsCents">Proceeds</SoldTH>
                  <SoldTH k="realizedPnlCents">Realized P&L</SoldTH>
                  <SoldTH k="lastSellDate">Sold</SoldTH>
                </tr>
              </thead>
              <tbody>
                {sortedSold.map((s) => {
                  const pnlColor = s.realizedPnlCents > 0
                    ? "text-terminal-positive"
                    : s.realizedPnlCents < 0
                    ? "text-terminal-negative"
                    : "text-terminal-text-tertiary";
                  const pnlPct = s.totalCostCents !== 0
                    ? (s.realizedPnlCents / s.totalCostCents) * 100
                    : 0;
                  return (
                    <tr
                      key={`${s.accountId}-${s.securityId}`}
                      className="border-t border-terminal-border hover:bg-terminal-bg-secondary/50 transition-colors"
                    >
                      <td className="px-4 py-2 font-mono text-sm">
                        <TickerLink ticker={s.ticker} />
                      </td>
                      <td className="px-4 py-2 text-sm">{s.name}</td>
                      <td className="px-4 py-2 text-xs text-terminal-text-secondary">{s.accountName}</td>
                      <td className="px-4 py-2">
                        <span className={`text-xs px-2 py-0.5 rounded font-mono ${
                          s.assetClass === "stock" ? "bg-terminal-info/20 text-terminal-info"
                            : s.assetClass === "etf" ? "bg-terminal-accent/20 text-terminal-accent"
                            : s.assetClass === "crypto" ? "bg-terminal-warning/20 text-terminal-warning"
                            : "bg-terminal-bg-tertiary text-terminal-text-tertiary"
                        }`}>
                          {s.assetClass}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-sm">
                        <Private>{formatCurrency(s.totalCostCents, s.currency)}</Private>
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-sm">
                        <Private>{formatCurrency(s.totalProceedsCents, s.currency)}</Private>
                      </td>
                      <td className={`px-4 py-2 text-right font-mono text-sm ${pnlColor}`}>
                        <Private>
                          {formatCurrency(s.realizedPnlCents, s.currency)}
                          <span className="text-xs ml-1">({formatPercent(pnlPct, true)})</span>
                        </Private>
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-sm text-terminal-text-secondary">
                        {s.lastSellDate || "--"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
