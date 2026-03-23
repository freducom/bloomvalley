"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGetRaw, apiPost } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/format";
import { TickerLink } from "@/components/ui/TickerLink";

/* ── Types ── */

interface InsiderTrade {
  id: number;
  securityId: number;
  ticker: string | null;
  securityName: string | null;
  insiderName: string;
  role: string;
  tradeType: string;
  jurisdiction: string;
  tradeDate: string;
  disclosureDate: string;
  shares: string;
  priceCents: number | null;
  valueCents: number | null;
  currency: string;
  sharesAfter: string | null;
  sourceUrl: string | null;
  isSignificant: boolean;
}

interface Signal {
  type: string;
  severity: string;
  ticker: string;
  securityName: string;
  message: string;
  tradeDate?: string;
  valueCents?: number;
  currency?: string;
}

interface CongressTradeItem {
  id: number;
  memberName: string;
  party: string;
  chamber: string;
  state: string | null;
  tradeType: string;
  tradeDate: string;
  disclosureDate: string;
  disclosureLagDays: number;
  amountRangeLowCents: number;
  amountRangeHighCents: number;
  currency: string;
  tickerReported: string;
  assetDescription: string | null;
}

interface BuybackItem {
  id: number;
  ticker: string;
  name: string;
  announcedDate: string;
  authorizedAmountCents: number | null;
  authorizedShares: number | null;
  executedAmountCents: number;
  executedShares: number;
  currency: string;
  status: string;
  progressPct: number;
}

type Tab = "trades" | "signals" | "congress" | "buybacks";

const TRADE_TYPE_COLORS: Record<string, string> = {
  buy: "text-terminal-positive bg-terminal-positive/10",
  sell: "text-terminal-negative bg-terminal-negative/10",
  exercise: "text-terminal-info bg-terminal-info/10",
  gift: "text-terminal-warning bg-terminal-warning/10",
};

const ROLE_LABELS: Record<string, string> = {
  ceo: "CEO",
  cfo: "CFO",
  cto: "CTO",
  coo: "COO",
  director: "Director",
  board_chair: "Board Chair",
  vp: "VP",
  other_executive: "Executive",
  related_party: "Related",
};

const JURISDICTION_FLAGS: Record<string, string> = {
  fi: "FI",
  se: "SE",
  us: "US",
};

const PARTY_COLORS: Record<string, string> = {
  democrat: "text-blue-400 bg-blue-900/30",
  republican: "text-red-400 bg-red-900/30",
  independent: "text-terminal-text-secondary bg-terminal-bg-tertiary",
};

const STATUS_COLORS: Record<string, string> = {
  announced: "text-terminal-info",
  active: "text-terminal-positive",
  completed: "text-terminal-text-secondary",
  cancelled: "text-terminal-negative",
};

export default function InsiderPage() {
  const [tab, setTab] = useState<Tab>("trades");

  const tabs: { key: Tab; label: string }[] = [
    { key: "trades", label: "Insider Trades" },
    { key: "signals", label: "Signals" },
    { key: "congress", label: "Congress" },
    { key: "buybacks", label: "Buybacks" },
  ];

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Insider Tracking</h1>

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

      {tab === "trades" && <TradesTab />}
      {tab === "signals" && <SignalsTab />}
      {tab === "congress" && <CongressTab />}
      {tab === "buybacks" && <BuybacksTab />}
    </div>
  );
}

/* ── Trades Tab ── */

function TradesTab() {
  const [trades, setTrades] = useState<InsiderTrade[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filterJurisdiction, setFilterJurisdiction] = useState("");
  const [filterType, setFilterType] = useState("");
  const [significantOnly, setSignificantOnly] = useState(false);

  const loadTrades = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterJurisdiction) params.set("jurisdiction", filterJurisdiction);
      if (filterType) params.set("tradeType", filterType);
      if (significantOnly) params.set("isSignificant", "true");
      params.set("limit", "200");
      const res = await apiGetRaw<{ data: InsiderTrade[]; pagination: { total: number } }>(
        `/insiders/trades?${params}`
      );
      setTrades(res.data);
      setTotal(res.pagination.total);
    } catch { /* */ }
    setLoading(false);
  }, [filterJurisdiction, filterType, significantOnly]);

  useEffect(() => { loadTrades(); }, [loadTrades]);

  return (
    <div>
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={filterJurisdiction}
          onChange={(e) => setFilterJurisdiction(e.target.value)}
          className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
        >
          <option value="">All jurisdictions</option>
          <option value="fi">Finland</option>
          <option value="se">Sweden</option>
          <option value="us">United States</option>
        </select>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
        >
          <option value="">All types</option>
          <option value="buy">Buy</option>
          <option value="sell">Sell</option>
          <option value="exercise">Exercise</option>
        </select>
        <label className="flex items-center gap-1.5 text-sm text-terminal-text-secondary">
          <input
            type="checkbox"
            checked={significantOnly}
            onChange={(e) => setSignificantOnly(e.target.checked)}
            className="accent-terminal-accent"
          />
          Significant only
        </label>
        <span className="text-sm text-terminal-text-secondary self-center ml-auto">
          {total} trade{total !== 1 ? "s" : ""}
        </span>
      </div>

      {loading ? (
        <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>
      ) : trades.length === 0 ? (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
          <p className="text-terminal-text-secondary text-sm">
            No insider trades recorded yet. Add trades manually or connect a data pipeline.
          </p>
        </div>
      ) : (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
                <th className="text-left p-3">Date</th>
                <th className="text-left p-3">Security</th>
                <th className="text-left p-3">Insider</th>
                <th className="text-left p-3">Role</th>
                <th className="text-center p-3">Type</th>
                <th className="text-right p-3">Shares</th>
                <th className="text-right p-3">Value</th>
                <th className="text-center p-3">Jur.</th>
                <th className="text-center p-3">Sig.</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr
                  key={t.id}
                  className={`border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary ${
                    t.isSignificant ? "bg-terminal-warning/5" : ""
                  }`}
                >
                  <td className="p-3 text-xs whitespace-nowrap">{formatDate(t.tradeDate)}</td>
                  <td className="p-3">
                    {t.ticker && <TickerLink ticker={t.ticker} />}
                  </td>
                  <td className="p-3 text-xs">{t.insiderName}</td>
                  <td className="p-3 text-xs text-terminal-text-secondary">
                    {ROLE_LABELS[t.role] || t.role}
                  </td>
                  <td className="text-center p-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${TRADE_TYPE_COLORS[t.tradeType] || ""}`}>
                      {t.tradeType.toUpperCase()}
                    </span>
                  </td>
                  <td className="text-right p-3 font-mono text-xs">
                    {parseFloat(t.shares).toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  </td>
                  <td className="text-right p-3 font-mono text-xs">
                    {t.valueCents ? formatCurrency(t.valueCents, t.currency) : "-"}
                  </td>
                  <td className="text-center p-3">
                    <span className="text-xs px-1.5 py-0.5 rounded bg-terminal-bg-tertiary text-terminal-text-secondary">
                      {JURISDICTION_FLAGS[t.jurisdiction] || t.jurisdiction}
                    </span>
                  </td>
                  <td className="text-center p-3">
                    {t.isSignificant && (
                      <span className="text-terminal-warning text-xs" title="Significant trade">!</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── Signals Tab ── */

function SignalsTab() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: Signal[] }>("/insiders/signals");
        setSignals(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (signals.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No significant insider signals detected in the last 30 days.
        </p>
        <p className="text-xs text-terminal-text-secondary mt-2">
          Signals include cluster buying (3+ insiders within 30 days), CEO/CFO buys, and large transactions (&gt;€100k).
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {signals.map((sig, i) => (
        <div
          key={i}
          className={`border rounded bg-terminal-bg-secondary p-4 ${
            sig.severity === "high"
              ? "border-terminal-warning"
              : "border-terminal-border"
          }`}
        >
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                sig.type === "cluster_buying"
                  ? "bg-terminal-warning/20 text-terminal-warning"
                  : "bg-terminal-info/20 text-terminal-info"
              }`}>
                {sig.type === "cluster_buying" ? "CLUSTER BUY" : "INSIDER TRADE"}
              </span>
              <TickerLink ticker={sig.ticker} />
              <span className="text-xs text-terminal-text-secondary">{sig.securityName}</span>
            </div>
            {sig.tradeDate && (
              <span className="text-xs text-terminal-text-secondary">{formatDate(sig.tradeDate)}</span>
            )}
          </div>
          <p className="text-sm text-terminal-text-primary">{sig.message}</p>
          {sig.valueCents && (
            <p className="text-xs text-terminal-text-secondary mt-1">
              Value: {formatCurrency(sig.valueCents, sig.currency || "EUR")}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/* ── Congress Tab ── */

function CongressTab() {
  const [trades, setTrades] = useState<CongressTradeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filterParty, setFilterParty] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (filterParty) params.set("party", filterParty);
        params.set("limit", "200");
        const res = await apiGetRaw<{ data: CongressTradeItem[]; pagination: { total: number } }>(
          `/insiders/congress?${params}`
        );
        setTrades(res.data);
        setTotal(res.pagination.total);
      } catch { /* */ }
      setLoading(false);
    })();
  }, [filterParty]);

  return (
    <div>
      <div className="flex gap-3 mb-4">
        <select
          value={filterParty}
          onChange={(e) => setFilterParty(e.target.value)}
          className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
        >
          <option value="">All parties</option>
          <option value="democrat">Democrat</option>
          <option value="republican">Republican</option>
          <option value="independent">Independent</option>
        </select>
        <span className="text-sm text-terminal-text-secondary self-center">{total} trade{total !== 1 ? "s" : ""}</span>
      </div>

      {loading ? (
        <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>
      ) : trades.length === 0 ? (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
          <p className="text-terminal-text-secondary text-sm">
            No congress trades recorded. Data sourced from STOCK Act disclosures via Quiver Quantitative.
          </p>
        </div>
      ) : (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
                <th className="text-left p-3">Member</th>
                <th className="text-center p-3">Party</th>
                <th className="text-center p-3">Chamber</th>
                <th className="text-center p-3">Type</th>
                <th className="text-left p-3">Security</th>
                <th className="text-right p-3">Amount Range</th>
                <th className="text-left p-3">Trade Date</th>
                <th className="text-right p-3">Lag</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
                  <td className="p-3 text-xs">{t.memberName}</td>
                  <td className="text-center p-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${PARTY_COLORS[t.party] || ""}`}>
                      {t.party.charAt(0).toUpperCase()}
                    </span>
                  </td>
                  <td className="text-center p-3 text-xs capitalize">{t.chamber}</td>
                  <td className="text-center p-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${TRADE_TYPE_COLORS[t.tradeType] || ""}`}>
                      {t.tradeType.toUpperCase()}
                    </span>
                  </td>
                  <td className="p-3 font-mono text-xs"><TickerLink ticker={t.tickerReported} /></td>
                  <td className="text-right p-3 font-mono text-xs">
                    {formatCurrency(t.amountRangeLowCents, t.currency)} &ndash; {formatCurrency(t.amountRangeHighCents, t.currency)}
                  </td>
                  <td className="p-3 text-xs">{formatDate(t.tradeDate)}</td>
                  <td className={`text-right p-3 text-xs font-mono ${
                    t.disclosureLagDays > 45 ? "text-terminal-negative" : "text-terminal-text-secondary"
                  }`}>
                    {t.disclosureLagDays}d
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── Buybacks Tab ── */

function BuybacksTab() {
  const [buybacks, setBuybacks] = useState<BuybackItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: BuybackItem[] }>("/insiders/buybacks");
        setBuybacks(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (buybacks.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No share buyback programs tracked. Programs are added from company announcements.
        </p>
      </div>
    );
  }

  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
            <th className="text-left p-3">Security</th>
            <th className="text-right p-3">Authorized</th>
            <th className="text-right p-3">Executed</th>
            <th className="p-3 w-32">Progress</th>
            <th className="text-center p-3">Status</th>
            <th className="text-left p-3">Announced</th>
          </tr>
        </thead>
        <tbody>
          {buybacks.map((bb) => (
            <tr key={bb.id} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
              <td className="p-3">
                <TickerLink ticker={bb.ticker} className="font-mono text-terminal-accent mr-2 hover:underline" />
                <span className="text-xs text-terminal-text-secondary">{bb.name}</span>
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {bb.authorizedAmountCents
                  ? formatCurrency(bb.authorizedAmountCents, bb.currency)
                  : bb.authorizedShares
                    ? `${bb.authorizedShares.toLocaleString()} shares`
                    : "-"}
              </td>
              <td className="text-right p-3 font-mono text-xs">
                {bb.executedAmountCents
                  ? formatCurrency(bb.executedAmountCents, bb.currency)
                  : bb.executedShares
                    ? `${bb.executedShares.toLocaleString()} shares`
                    : "-"}
              </td>
              <td className="p-3">
                <div className="relative h-3 bg-terminal-bg-tertiary rounded overflow-hidden">
                  <div
                    className="h-full bg-terminal-accent/60 rounded"
                    style={{ width: `${Math.min(bb.progressPct, 100)}%` }}
                  />
                </div>
                <span className="text-[10px] text-terminal-text-secondary">{bb.progressPct}%</span>
              </td>
              <td className="text-center p-3">
                <span className={`text-xs capitalize ${STATUS_COLORS[bb.status] || ""}`}>
                  {bb.status}
                </span>
              </td>
              <td className="p-3 text-xs">{formatDate(bb.announcedDate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
