"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { apiGet, apiGetRaw } from "@/lib/api";
import { formatCurrency, formatPercent, formatDate, formatLargeNumber } from "@/lib/format";
import { Private } from "@/lib/privacy";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const gfmOptions = { singleTilde: false };

/* ── AI Analysis markdown components ── */

function textOf(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (!node) return "";
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) {
    const el = node as React.ReactElement<{ children?: React.ReactNode }>;
    return textOf(el.props?.children);
  }
  return "";
}

function detectVerdict(text: string): string | null {
  const m = text.match(/\b(buy|sell|hold|wait|avoid|accumulate|trim|strong buy|strong sell)\b/i);
  return m ? m[1].toUpperCase() : null;
}

const VERDICT_COLORS: Record<string, string> = {
  BUY: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  "STRONG BUY": "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  ACCUMULATE: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  HOLD: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  WAIT: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  SELL: "bg-red-500/20 text-red-400 border-red-500/40",
  "STRONG SELL": "bg-red-500/20 text-red-400 border-red-500/40",
  TRIM: "bg-red-500/20 text-red-400 border-red-500/40",
  AVOID: "bg-red-500/20 text-red-400 border-red-500/40",
};

/* eslint-disable @typescript-eslint/no-explicit-any */
const analysisComponents: Record<string, React.ComponentType<any>> = {
  strong({ children, node, ...rest }: any) {
    void node;
    const text = textOf(children).trim().toLowerCase();
    if (/^bull\s*case/.test(text))
      return <strong className="text-emerald-400" {...rest}>{children}</strong>;
    if (/^bear\s*case/.test(text))
      return <strong className="text-red-400" {...rest}>{children}</strong>;
    if (/^verdict/.test(text)) {
      const verdict = detectVerdict(textOf(children));
      const cls = VERDICT_COLORS[verdict || ""] || "text-terminal-accent";
      return <strong className={cls} {...rest}>{children}</strong>;
    }
    return <strong {...rest}>{children}</strong>;
  },

  h3({ children, node, ...rest }: any) {
    void node;
    const text = textOf(children).trim().toLowerCase();
    if (/^bull\s*case/.test(text))
      return <h3 className="text-emerald-400 font-semibold mt-3 mb-1" {...rest}>{children}</h3>;
    if (/^bear\s*case/.test(text))
      return <h3 className="text-red-400 font-semibold mt-3 mb-1" {...rest}>{children}</h3>;
    if (/^verdict/.test(text)) {
      const verdict = detectVerdict(textOf(children));
      const cls = VERDICT_COLORS[verdict || ""] || "bg-terminal-accent/20 text-terminal-accent border-terminal-accent/40";
      return <div className={`mt-3 mb-1 inline-block px-3 py-1.5 rounded border text-sm font-bold ${cls}`} {...rest}>{children}</div>;
    }
    return <h3 className="font-semibold mt-3 mb-1" {...rest}>{children}</h3>;
  },

  p({ children, node, ...rest }: any) {
    void node;
    const text = textOf(children).trim();
    if (/^verdict/i.test(text.replace(/^\*\*/, ""))) {
      const verdict = detectVerdict(text);
      const cls = VERDICT_COLORS[verdict || ""] || "bg-terminal-accent/20 text-terminal-accent border-terminal-accent/40";
      return <div className={`mt-3 mb-2 px-3 py-2 rounded border text-sm font-medium ${cls}`} {...rest}>{children}</div>;
    }
    return <p {...rest}>{children}</p>;
  },
};
/* eslint-enable @typescript-eslint/no-explicit-any */

/* ── Types ── */

interface Security {
  id: number;
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  currency: string;
  assetClass: string;
}

interface OhlcPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface Fundamentals {
  id: number;
  securityId: number;
  ticker: string;
  securityName: string;
  assetClass: string;
  currency: string;
  priceToBook: number | null;
  peRatio: number | null;
  roic: number | null;
  wacc: number | null;
  roe: number | null;
  fcfYield: number | null;
  netDebtEbitda: number | null;
  dividendYield: number | null;
  grossMargin: number | null;
  operatingMargin: number | null;
  netMargin: number | null;
  dcfValueCents: number | null;
  dcfUpsidePct: number | null;
  dcfModelNotes: string | null;
  currentPriceCents: number | null;
  marketCapCents: number | null;
  freeCashFlowCents: number | null;
  fcfCurrency: string | null;
  epsCents: number | null;
  revenueCents: number | null;
  shortInterestPct: number | null;
  updatedAt: string;
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
  marketValueCents: number | null;
  marketValueEurCents: number | null;
  costBasisEurCents: number | null;
  unrealizedPnlCents: number | null;
  unrealizedPnlPct: number | null;
  currency: string;
}

interface Recommendation {
  id: number;
  securityId: number;
  ticker: string;
  securityName: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: "high" | "medium" | "low";
  rationale: string;
  bullCase: string | null;
  bearCase: string | null;
  targetPriceCents: number | null;
  status: string;
  createdAt: string;
}

interface ResearchNote {
  id: number;
  securityId: number;
  ticker: string;
  title: string | null;
  thesis: string | null;
  summary: string | null;
  bullCase: string | null;
  bearCase: string | null;
  tags?: string[];
  createdAt: string;
  updatedAt: string;
}

interface InsiderTrade {
  id: number;
  securityId: number;
  ticker: string;
  insiderName: string;
  tradeType: string;
  shares: number;
  priceCents: number | null;
  valueCents: number | null;
  currency: string | null;
  tradeDate: string;
}

interface NewsItem {
  id: number;
  securityId: number | null;
  title: string;
  url: string | null;
  source: string | null;
  publishedAt: string;
}

interface DividendEvent {
  securityId: number;
  ticker: string | null;
  exDate: string | null;
  paymentDate: string | null;
  amountPerShareCents: number | null;
  currency: string | null;
  frequency: string | null;
}

/* ── Helpers ── */

function MetricCell({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: string;
  colorClass?: string;
}) {
  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-3">
      <div className="text-xs text-terminal-text-secondary">{label}</div>
      <div className={`font-mono text-sm mt-1 ${colorClass || ""}`}>{value}</div>
    </div>
  );
}

function roicColor(v: number | null): string {
  if (v === null) return "";
  if (v > 0.15) return "text-terminal-positive";
  if (v >= 0.10) return "text-terminal-warning";
  return "text-terminal-negative";
}

function fcfYieldColor(v: number | null): string {
  if (v === null) return "";
  return v > 0.05 ? "text-terminal-positive" : "";
}

function debtColor(v: number | null): string {
  if (v === null) return "";
  return v > 3 ? "text-terminal-negative" : "";
}

function dcfColor(v: number | null): string {
  if (v === null) return "";
  return v >= 0 ? "text-terminal-positive" : "text-terminal-negative";
}

/* ── Price Sparkline ── */

function PriceSparkline({ data }: { data: OhlcPoint[] }) {
  // Take last 60 trading days
  const points = data.slice(-60);
  if (points.length === 0) return null;

  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;

  const width = 100;
  const height = 40;
  const stepX = width / (closes.length - 1 || 1);

  const pathPoints = closes
    .map((c, i) => {
      const x = i * stepX;
      const y = height - ((c - min) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");

  const isUp = closes[closes.length - 1] >= closes[0];

  return (
    <div className="w-full">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="w-full h-20"
      >
        <polyline
          fill="none"
          stroke={isUp ? "var(--color-terminal-positive, #22c55e)" : "var(--color-terminal-negative, #ef4444)"}
          strokeWidth="1"
          points={pathPoints}
        />
      </svg>
      <div className="flex justify-between text-xs text-terminal-text-tertiary font-mono mt-1">
        <span>{points[0]?.date}</span>
        <span>{points[points.length - 1]?.date}</span>
      </div>
    </div>
  );
}

/* ── Main Component ── */

export default function SecurityDetailPage() {
  const params = useParams();
  const router = useRouter();
  const ticker = (params.ticker as string)?.toUpperCase() || "";

  const [loading, setLoading] = useState(true);
  const [security, setSecurity] = useState<Security | null>(null);
  const [ohlc, setOhlc] = useState<OhlcPoint[] | null>(null);
  const [fundamentals, setFundamentals] = useState<Fundamentals | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [research, setResearch] = useState<ResearchNote[]>([]);
  const [insiders, setInsiders] = useState<InsiderTrade[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [dividends, setDividends] = useState<DividendEvent[]>([]);
  const analystExcerpt: string | null = null; // kept for template compat
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;

    const load = async () => {
      try {
        // Step 1: Look up security by ticker
        const secResult = await apiGetRaw<{ data: Security[] }>(
          `/securities?ticker=${encodeURIComponent(ticker)}`
        );

        if (!secResult.data || secResult.data.length === 0) {
          setError(`Security not found: ${ticker}`);
          setLoading(false);
          return;
        }

        const sec = secResult.data[0];
        setSecurity(sec);
        const id = sec.id;

        // Step 2: Fetch everything in parallel
        const [
          ohlcRes,
          fundRes,
          holdRes,
          recRes,
          researchRes,
          insiderRes,
          newsRes,
          divRes,
        ] = await Promise.all([
          apiGetRaw<{ data: OhlcPoint[] }>(`/charts/${id}/ohlc?period=1Y`).catch(() => null),
          apiGetRaw<{ data: Fundamentals[] }>(`/fundamentals?securityId=${id}`).catch(() => null),
          apiGet<Holding[]>("/portfolio/holdings").catch(() => null),
          apiGetRaw<{ data: Recommendation[] }>("/recommendations?status=active&limit=50").catch(() => null),
          apiGetRaw<{ data: ResearchNote[] }>(`/research/notes?securityId=${id}`).catch(() => null),
          apiGetRaw<{ data: InsiderTrade[] }>(`/insiders/trades?securityId=${id}`).catch(() => null),
          apiGetRaw<{ data: NewsItem[] }>(`/news?securityId=${id}&limit=10`).catch(() => null),
          apiGetRaw<{ data: DividendEvent[] }>(`/dividends/history?securityId=${id}`).catch(() => null),
        ]);

        if (ohlcRes?.data) setOhlc(ohlcRes.data);
        if (fundRes?.data && fundRes.data.length > 0) setFundamentals(fundRes.data[0]);
        if (holdRes) setHoldings(holdRes.filter((h) => h.securityId === id));
        if (recRes?.data) setRecommendations(recRes.data.filter((r) => r.ticker === ticker));
        if (researchRes?.data) setResearch(researchRes.data.filter((n) => {
              const tags = n.tags || [];
              // Exclude machine-generated data notes that contain raw JSON, not prose
              const dataTags = ["sec_filing", "etf_profile", "justetf", "fund_rating", "morningstar"];
              return !dataTags.some((t) => tags.includes(t));
            }));
        if (insiderRes?.data) setInsiders(insiderRes.data);
        if (newsRes?.data) setNews(newsRes.data);
        if (divRes?.data) setDividends(divRes.data);

        // analystExcerpt extraction removed — per-security notes are now
        // extracted by the swarm and stored individually
      } catch (e) {
        console.error("Failed to load security detail:", e);
        setError("Failed to load security data");
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [ticker]);

  /* ── Loading state ── */
  if (loading) {
    return (
      <div className="animate-pulse">
        <div className="h-5 bg-terminal-bg-secondary rounded w-20 mb-4" />
        <div className="h-8 bg-terminal-bg-secondary rounded w-64 mb-6" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-20 bg-terminal-bg-secondary rounded" />
          ))}
        </div>
      </div>
    );
  }

  /* ── Error state ── */
  if (error || !security) {
    return (
      <div>
        <button
          onClick={() => router.back()}
          className="text-sm text-terminal-accent hover:underline font-mono mb-6 inline-block"
        >
          &larr; Back
        </button>
        <div className="flex items-center justify-center h-64 border border-terminal-border rounded-md bg-terminal-bg-secondary">
          <div className="text-center">
            <p className="text-lg text-terminal-text-secondary mb-2">
              {error || "Security not found"}
            </p>
            <p className="text-sm text-terminal-text-tertiary">
              Check the ticker and try again.
            </p>
          </div>
        </div>
      </div>
    );
  }

  /* ── Derived data ── */
  const isHeld = holdings.length > 0;
  // Most recent research-analyst and technical notes (API returns newest first)
  const latestResearchAnalyst = research
    .find((n) => n.tags?.includes("research-analyst")) || null;
  const latestTechnical = research
    .find((n) => n.tags?.includes("technical-analyst")) || null;
  const latestResearch = latestResearchAnalyst || latestTechnical || (research.length > 0 ? research[0] : null);
  const latestRec = recommendations.length > 0 ? recommendations[0] : null;

  const currentPrice = fundamentals?.currentPriceCents ?? null;
  const currency = security.currency || "EUR";

  // 52-week range from OHLC data
  let high52w: number | null = null;
  let low52w: number | null = null;
  let dayChange: number | null = null;
  let dayChangePct: number | null = null;

  if (ohlc && ohlc.length > 0) {
    high52w = Math.max(...ohlc.map((p) => p.high));
    low52w = Math.min(...ohlc.map((p) => p.low));
    if (ohlc.length >= 2) {
      const last = ohlc[ohlc.length - 1];
      const prev = ohlc[ohlc.length - 2];
      dayChange = last.close - prev.close;
      dayChangePct = prev.close !== 0 ? (dayChange / prev.close) * 100 : null;
    }
  }

  const holdingStatus = isHeld ? "HELD" : "NOT HELD";
  const holdingBadgeClass = isHeld
    ? "bg-terminal-positive/20 text-terminal-positive"
    : "bg-terminal-bg-tertiary text-terminal-text-tertiary";

  return (
    <div>
      {/* Back link */}
      <button
        onClick={() => router.back()}
        className="text-sm text-terminal-accent hover:underline font-mono mb-4 inline-block"
      >
        &larr; Back
      </button>

      {/* ── Header ── */}
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-3xl font-bold font-mono text-terminal-accent">
              {security.ticker}
            </h1>
            <span className={`text-xs font-mono font-semibold px-2 py-0.5 rounded ${holdingBadgeClass}`}>
              {holdingStatus}
            </span>
          </div>
          <p className="text-lg text-terminal-text-primary">{security.name}</p>
          <div className="flex items-center gap-3 mt-1 text-sm text-terminal-text-secondary">
            {security.sector && <span>{security.sector}</span>}
            {security.exchange && (
              <>
                <span className="text-terminal-border">|</span>
                <span>{security.exchange}</span>
              </>
            )}
            <span className="text-terminal-border">|</span>
            <span className="font-mono">{currency}</span>
            <span className="text-terminal-border">|</span>
            <span className="capitalize">{security.assetClass}</span>
          </div>

          {/* If held — show summary */}
          {isHeld && (
            <div className="flex items-center gap-6 mt-3 text-sm">
              {holdings.map((h, idx) => {
                const pnlColor =
                  (h.unrealizedPnlCents ?? 0) > 0
                    ? "text-terminal-positive"
                    : (h.unrealizedPnlCents ?? 0) < 0
                    ? "text-terminal-negative"
                    : "text-terminal-text-tertiary";
                return (
                  <div key={idx} className="flex items-center gap-4 font-mono text-xs">
                    <span className="text-terminal-text-secondary">{h.accountName}</span>
                    <span>
                      Qty: <Private>{parseFloat(h.quantity).toLocaleString("en-US", { maximumFractionDigits: 4 })}</Private>
                    </span>
                    <span>
                      Cost: <Private>{formatCurrency(h.avgCostCents, h.currency)}</Private>
                    </span>
                    {h.marketValueEurCents != null && (
                      <span>
                        Value: <Private>{formatCurrency(h.marketValueEurCents)}</Private>
                      </span>
                    )}
                    {h.unrealizedPnlCents != null && (
                      <span className={pnlColor}>
                        P&L: <Private>{formatCurrency(h.unrealizedPnlCents)}</Private>
                        {h.unrealizedPnlPct != null && (
                          <> (<Private>{formatPercent(h.unrealizedPnlPct, true)}</Private>)</>
                        )}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Current price block */}
        <div className="text-right md:text-right">
          {currentPrice != null && (
            <div className="text-2xl font-mono font-bold">
              {formatCurrency(currentPrice, currency)}
            </div>
          )}
          {dayChange !== null && dayChangePct !== null && (
            <div
              className={`text-sm font-mono ${
                dayChange >= 0 ? "text-terminal-positive" : "text-terminal-negative"
              }`}
            >
              {dayChange >= 0 ? "+" : ""}
              {(dayChange / 100).toFixed(2)} ({formatPercent(dayChangePct, true)})
            </div>
          )}
          {high52w !== null && low52w !== null && (
            <div className="text-xs text-terminal-text-secondary font-mono mt-1">
              52w: {formatCurrency(Math.round(low52w * 100), currency)} &ndash;{" "}
              {formatCurrency(Math.round(high52w * 100), currency)}
            </div>
          )}
        </div>
      </div>

      {/* ── AI Analysis ── */}
      {(latestResearch?.thesis || analystExcerpt || latestRec?.rationale) && (
        <div className="border border-terminal-accent/30 bg-terminal-accent/5 rounded-md p-4 mb-6">
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="text-sm font-semibold text-terminal-accent">AI Analysis</h2>
            {latestResearch?.createdAt && (
              <span className="text-xs text-terminal-text-muted">
                {new Date(latestResearch.createdAt).toLocaleDateString("fi-FI")}
              </span>
            )}
          </div>
          {(latestResearch?.thesis || analystExcerpt) ? (
            <div className="text-sm text-terminal-text-primary leading-relaxed prose prose-invert prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-headings:text-terminal-text-primary prose-headings:mt-3 prose-headings:mb-1 prose-strong:text-terminal-text-primary">
              <ReactMarkdown remarkPlugins={[[remarkGfm, gfmOptions]]} components={analysisComponents}>
                {(latestResearch?.thesis || analystExcerpt || "")
                  .replace(/^#{2,3} (?:W-)?\d+\.\s+\S+\s*—[^\n]*\n*/m, "")
                  .replace(/\n---\s*$/g, "")
                  .trim()}
              </ReactMarkdown>
            </div>
          ) : (
            <>
              {latestRec?.rationale && (
                <p className="text-sm text-terminal-text-primary mb-2">{latestRec.rationale}</p>
              )}
              {latestRec?.bullCase && (
                <div className="mt-2">
                  <span className="text-xs font-semibold text-terminal-positive">Bull Case</span>
                  <p className="text-sm text-terminal-text-secondary mt-0.5">{latestRec.bullCase}</p>
                </div>
              )}
              {latestRec?.bearCase && (
                <div className="mt-2">
                  <span className="text-xs font-semibold text-terminal-negative">Bear Case</span>
                  <p className="text-sm text-terminal-text-secondary mt-0.5">{latestRec.bearCase}</p>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Technical Analysis (separate from research) ── */}
      {latestTechnical && latestTechnical !== latestResearch && latestTechnical.thesis && (
        <div className="border border-terminal-border bg-terminal-bg-secondary rounded-md p-4 mb-6">
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="text-sm font-semibold text-terminal-text-secondary">Technical Analysis</h2>
            {latestTechnical.createdAt && (
              <span className="text-xs text-terminal-text-muted">
                {new Date(latestTechnical.createdAt).toLocaleDateString("fi-FI")}
              </span>
            )}
          </div>
          <div className="text-sm text-terminal-text-primary leading-relaxed prose prose-invert prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-headings:text-terminal-text-primary prose-headings:mt-3 prose-headings:mb-1 prose-strong:text-terminal-text-primary">
            <ReactMarkdown remarkPlugins={[[remarkGfm, gfmOptions]]} components={analysisComponents}>
              {latestTechnical.thesis
                .replace(/^#{2,3} \d+\.\s+\S+\s*—[^\n]*\n*/m, "")
                .replace(/\n---\s*$/g, "")
                .trim()}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {/* ── Price Chart ── */}
      {ohlc && ohlc.length > 0 && (
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4 mb-6">
          <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">
            Price History (1Y)
          </h2>
          <PriceSparkline data={ohlc} />
        </div>
      )}

      {/* ── Fundamentals Grid ── */}
      {fundamentals && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">Fundamentals</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            <MetricCell
              label="ROIC"
              value={fundamentals.roic !== null ? formatPercent(fundamentals.roic * 100) : "-"}
              colorClass={roicColor(fundamentals.roic)}
            />
            <MetricCell
              label="P/B"
              value={fundamentals.priceToBook !== null ? fundamentals.priceToBook.toFixed(2) : "-"}
            />
            <MetricCell
              label="PE Ratio"
              value={fundamentals.peRatio !== null ? fundamentals.peRatio.toFixed(1) : "-"}
            />
            <MetricCell
              label="FCF Yield"
              value={fundamentals.fcfYield !== null ? formatPercent(fundamentals.fcfYield * 100) : "-"}
              colorClass={fcfYieldColor(fundamentals.fcfYield)}
            />
            <MetricCell
              label="Net Debt / EBITDA"
              value={fundamentals.netDebtEbitda !== null ? `${fundamentals.netDebtEbitda.toFixed(1)}x` : "-"}
              colorClass={debtColor(fundamentals.netDebtEbitda)}
            />
            <MetricCell
              label="Dividend Yield"
              value={fundamentals.dividendYield !== null ? formatPercent(fundamentals.dividendYield * 100) : "-"}
            />
            <MetricCell
              label="Gross Margin"
              value={fundamentals.grossMargin !== null ? formatPercent(fundamentals.grossMargin * 100) : "-"}
            />
            <MetricCell
              label="Operating Margin"
              value={fundamentals.operatingMargin !== null ? formatPercent(fundamentals.operatingMargin * 100) : "-"}
            />
            <MetricCell
              label="DCF Value"
              value={fundamentals.dcfValueCents !== null ? formatLargeNumber(fundamentals.dcfValueCents, currency) : "-"}
            />
            <MetricCell
              label="DCF Upside"
              value={fundamentals.dcfUpsidePct !== null ? formatPercent(fundamentals.dcfUpsidePct, true) : "-"}
              colorClass={dcfColor(fundamentals.dcfUpsidePct)}
            />
            <MetricCell
              label="Market Cap"
              value={fundamentals.marketCapCents !== null ? formatLargeNumber(fundamentals.marketCapCents, currency) : "-"}
            />
            <MetricCell
              label="Short Interest"
              value={fundamentals.shortInterestPct !== null ? `${fundamentals.shortInterestPct.toFixed(2)}%` : "-"}
            />
          </div>
          {fundamentals.updatedAt && (
            <p className="text-xs text-terminal-text-tertiary mt-2">
              Updated: {formatDate(fundamentals.updatedAt)}
            </p>
          )}
        </div>
      )}

      {/* ── Holdings Detail ── */}
      {isHeld && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">Holdings</h2>
          <div className="border border-terminal-border rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-terminal-bg-secondary text-terminal-text-secondary text-xs">
                  <th className="text-left px-4 py-2 font-medium">Account</th>
                  <th className="text-left px-4 py-2 font-medium">Type</th>
                  <th className="text-right px-4 py-2 font-medium">Quantity</th>
                  <th className="text-right px-4 py-2 font-medium">Avg Cost</th>
                  <th className="text-right px-4 py-2 font-medium">Current Value</th>
                  <th className="text-right px-4 py-2 font-medium">Unrealized P&L</th>
                  <th className="text-right px-4 py-2 font-medium">P&L %</th>
                </tr>
              </thead>
              <tbody>
                {holdings.map((h, idx) => {
                  const pnlColor =
                    (h.unrealizedPnlCents ?? 0) > 0
                      ? "text-terminal-positive"
                      : (h.unrealizedPnlCents ?? 0) < 0
                      ? "text-terminal-negative"
                      : "text-terminal-text-tertiary";
                  return (
                    <tr
                      key={idx}
                      className="border-t border-terminal-border hover:bg-terminal-bg-secondary/50"
                    >
                      <td className="px-4 py-2">{h.accountName}</td>
                      <td className="px-4 py-2">
                        <span className="text-xs px-2 py-0.5 rounded bg-terminal-info/20 text-terminal-info font-mono">
                          {h.accountType}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        <Private>
                          {parseFloat(h.quantity).toLocaleString("en-US", {
                            maximumFractionDigits: 4,
                          })}
                        </Private>
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        <Private>{formatCurrency(h.avgCostCents, h.currency)}</Private>
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        <Private>
                          {h.marketValueEurCents != null
                            ? formatCurrency(h.marketValueEurCents)
                            : "--"}
                        </Private>
                      </td>
                      <td className={`px-4 py-2 text-right font-mono ${pnlColor}`}>
                        <Private>
                          {h.unrealizedPnlCents != null
                            ? formatCurrency(h.unrealizedPnlCents)
                            : "--"}
                        </Private>
                      </td>
                      <td className={`px-4 py-2 text-right font-mono ${pnlColor}`}>
                        <Private>
                          {h.unrealizedPnlPct != null
                            ? formatPercent(h.unrealizedPnlPct, true)
                            : "--"}
                        </Private>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Recommendations ── */}
      {recommendations.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">
            Active Recommendations
          </h2>
          <div className="border border-terminal-border rounded-md divide-y divide-terminal-border">
            {recommendations.map((rec) => (
              <div
                key={rec.id}
                className="p-4 bg-terminal-bg-secondary hover:bg-terminal-bg-secondary/70 transition-colors"
              >
                <div className="flex items-center gap-3 mb-2">
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
                  <span
                    className={`text-xs font-mono px-2 py-0.5 rounded ${
                      rec.confidence === "high"
                        ? "bg-terminal-positive/20 text-terminal-positive"
                        : rec.confidence === "medium"
                        ? "bg-terminal-warning/20 text-terminal-warning"
                        : "bg-terminal-bg-tertiary text-terminal-text-tertiary"
                    }`}
                  >
                    {rec.confidence}
                  </span>
                  {rec.targetPriceCents != null && (
                    <span className="text-xs font-mono text-terminal-text-secondary">
                      Target: {formatCurrency(rec.targetPriceCents, currency)}
                    </span>
                  )}
                  <span className="text-xs text-terminal-text-tertiary ml-auto">
                    {formatDate(rec.createdAt)}
                  </span>
                </div>
                <p className="text-sm text-terminal-text-primary">{rec.rationale}</p>
                {rec.bullCase && (
                  <p className="text-xs text-terminal-text-secondary mt-1">
                    <span className="text-terminal-positive font-semibold">Bull:</span>{" "}
                    {rec.bullCase}
                  </p>
                )}
                {rec.bearCase && (
                  <p className="text-xs text-terminal-text-secondary mt-1">
                    <span className="text-terminal-negative font-semibold">Bear:</span>{" "}
                    {rec.bearCase}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Recent News ── */}
      {news.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">Recent News</h2>
          <div className="border border-terminal-border rounded-md divide-y divide-terminal-border">
            {news.slice(0, 5).map((item) => (
              <div
                key={item.id}
                className="px-4 py-3 bg-terminal-bg-secondary hover:bg-terminal-bg-secondary/70 transition-colors"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-terminal-text-primary hover:text-terminal-accent"
                      >
                        {item.title}
                      </a>
                    ) : (
                      <span className="text-sm text-terminal-text-primary">{item.title}</span>
                    )}
                    {item.source && (
                      <span className="text-xs text-terminal-text-tertiary ml-2">
                        {item.source}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-terminal-text-tertiary whitespace-nowrap font-mono">
                    {formatDate(item.publishedAt)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Insider Trades ── */}
      {insiders.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">
            Insider Trades
          </h2>
          <div className="border border-terminal-border rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-terminal-bg-secondary text-terminal-text-secondary text-xs">
                  <th className="text-left px-4 py-2 font-medium">Date</th>
                  <th className="text-left px-4 py-2 font-medium">Insider</th>
                  <th className="text-left px-4 py-2 font-medium">Type</th>
                  <th className="text-right px-4 py-2 font-medium">Shares</th>
                  <th className="text-right px-4 py-2 font-medium">Value</th>
                </tr>
              </thead>
              <tbody>
                {insiders.slice(0, 10).map((trade) => (
                  <tr
                    key={trade.id}
                    className="border-t border-terminal-border hover:bg-terminal-bg-secondary/50"
                  >
                    <td className="px-4 py-2 font-mono text-xs">
                      {formatDate(trade.tradeDate)}
                    </td>
                    <td className="px-4 py-2 text-xs">{trade.insiderName}</td>
                    <td className="px-4 py-2">
                      <span
                        className={`text-xs font-mono font-semibold px-2 py-0.5 rounded ${
                          trade.tradeType.toLowerCase().includes("buy") ||
                          trade.tradeType.toLowerCase().includes("purchase")
                            ? "bg-terminal-positive/20 text-terminal-positive"
                            : "bg-terminal-negative/20 text-terminal-negative"
                        }`}
                      >
                        {trade.tradeType}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {Number(trade.shares).toLocaleString("en-US", { maximumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {trade.valueCents != null
                        ? formatCurrency(trade.valueCents, trade.currency || currency)
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Dividends ── */}
      {dividends.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">
            Dividend Events
          </h2>
          <div className="border border-terminal-border rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-terminal-bg-secondary text-terminal-text-secondary text-xs">
                  <th className="text-left px-4 py-2 font-medium">Ex-Date</th>
                  <th className="text-left px-4 py-2 font-medium">Pay Date</th>
                  <th className="text-right px-4 py-2 font-medium">Amount</th>
                  <th className="text-left px-4 py-2 font-medium">Frequency</th>
                </tr>
              </thead>
              <tbody>
                {dividends.map((div, idx) => (
                  <tr
                    key={`${div.exDate}-${idx}`}
                    className="border-t border-terminal-border hover:bg-terminal-bg-secondary/50"
                  >
                    <td className="px-4 py-2 font-mono text-xs">
                      {div.exDate ? formatDate(div.exDate) : "-"}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {div.paymentDate ? formatDate(div.paymentDate) : "-"}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {div.amountPerShareCents != null
                        ? formatCurrency(div.amountPerShareCents, div.currency || currency)
                        : "-"}
                    </td>
                    <td className="px-4 py-2 text-xs text-terminal-text-secondary capitalize">
                      {div.frequency || "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Empty state when no additional data ── */}
      {!fundamentals && !ohlc && recommendations.length === 0 && news.length === 0 && (
        <div className="border border-terminal-border rounded-md bg-terminal-bg-secondary p-8 text-center">
          <p className="text-terminal-text-secondary text-sm">
            No detailed data available for {ticker} yet. Run the data pipelines and agent analysts to populate fundamentals, news, and recommendations.
          </p>
        </div>
      )}
    </div>
  );
}
