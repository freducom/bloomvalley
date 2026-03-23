"use client";

import { useEffect, useState, useCallback } from "react";
import { apiGet, apiGetRaw } from "@/lib/api";
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

export default function HoldingsPage() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [divMap, setDivMap] = useState<Record<number, number>>({}); // securityId -> 6-month income cents
  const [quoteMap, setQuoteMap] = useState<Record<number, LiveQuote>>({});
  const [quotesLoading, setQuotesLoading] = useState(false);
  const [quotesTime, setQuotesTime] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("marketValueEurCents");
  const [sortAsc, setSortAsc] = useState(false);
  const [filterAccount, setFilterAccount] = useState<string>("all");

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

  useEffect(() => {
    (async () => {
      try {
        const [holdingsData, divData] = await Promise.all([
          apiGet<Holding[]>("/portfolio/holdings"),
          apiGetRaw<{ data: { byHolding: DividendByHolding[] } }>("/dividends/income-projection")
            .catch(() => ({ data: { byHolding: [] } })),
        ]);
        setHoldings(holdingsData);
        // Build map: securityId -> 6-month projected income (annual / 2)
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
    })();
    fetchQuotes();
    const interval = setInterval(fetchQuotes, 5 * 60 * 1000); // 5 min refresh
    return () => clearInterval(interval);
  }, [fetchQuotes]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const arrow = (key: SortKey) => sortKey === key ? (sortAsc ? " ▲" : " ▼") : "";

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

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Holdings</h1>
        <div className="flex items-center gap-4">
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
        </div>
      </div>

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
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
