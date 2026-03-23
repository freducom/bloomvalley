"use client";

import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiGet, apiGetRaw, apiPost, apiPut } from "@/lib/api";
import { formatCurrency, formatDate, formatPercent } from "@/lib/format";
import { Private } from "@/lib/privacy";
import { TickerLink } from "@/components/ui/TickerLink";

/* ── Types ── */

interface Recommendation {
  id: number;
  securityId: number;
  ticker: string | null;
  securityName: string | null;
  action: string;
  confidence: string;
  targetPriceCents: number | null;
  entryPriceCents: number | null;
  currency: string;
  rationale: string;
  bullCase: string | null;
  bearCase: string | null;
  source: string | null;
  timeHorizon: string | null;
  status: string;
  recommendedDate: string;
  closedDate: string | null;
  expiryDate: string | null;
  exitPriceCents: number | null;
  returnPct: number | null;
  outcomeNotes: string | null;
  unrealizedReturnPct?: number;
  currentPriceCents?: number;
}

interface Retrospective {
  totalClosed: number;
  activeCount: number;
  hitRate: number | null;
  avgReturnPct: number | null;
  totalWins: number;
  totalLosses: number;
  byAction: Record<string, { count: number; hitRate: number; avgReturnPct: number }>;
  byConfidence: Record<string, { count: number; hitRate: number; avgReturnPct: number }>;
  bySource: Record<string, { count: number; hitRate: number; avgReturnPct: number }>;
  bestCalls: { id: number; securityId: number; action: string; returnPct: number }[];
  worstCalls: { id: number; securityId: number; action: string; returnPct: number }[];
}

interface SecurityOption {
  id: number;
  ticker: string;
  name: string;
}

type Tab = "active" | "closed" | "retrospective" | "create";

const ACTION_COLORS: Record<string, string> = {
  buy: "text-terminal-positive bg-terminal-positive/10",
  sell: "text-terminal-negative bg-terminal-negative/10",
  hold: "text-terminal-warning bg-terminal-warning/10",
};

const CONFIDENCE_COLORS: Record<string, string> = {
  high: "text-terminal-positive",
  medium: "text-terminal-warning",
  low: "text-terminal-text-secondary",
};

const HORIZON_LABELS: Record<string, string> = {
  short: "< 3m",
  medium: "3-12m",
  long: "> 12m",
};

export default function RecommendationsPage() {
  const [tab, setTab] = useState<Tab>("active");

  const tabs: { key: Tab; label: string }[] = [
    { key: "active", label: "Active" },
    { key: "closed", label: "Closed" },
    { key: "retrospective", label: "Retrospective" },
    { key: "create", label: "+ New" },
  ];

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Recommendations</h1>

      <div className="flex gap-1 mb-4 border-b border-terminal-border overflow-x-auto">
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

      {tab === "active" && <ActiveTab />}
      {tab === "closed" && <ClosedTab />}
      {tab === "retrospective" && <RetroTab />}
      {tab === "create" && <CreateTab onCreated={() => setTab("active")} />}
    </div>
  );
}

/* ── Portfolio Manager Brief ── */

function PortfolioManagerBrief() {
  const [note, setNote] = useState<AnalystNote | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: AnalystNote[] }>(
          "/research/notes?tag=portfolio-manager&limit=1"
        );
        if (res.data.length > 0) setNote(res.data[0]);
      } catch { /* */ }
    })();
  }, []);

  if (!note) return null;

  const dateStr = (() => {
    const d = new Date(note.createdAt);
    return `${d.getDate()}.${d.getMonth() + 1}.${d.getFullYear()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  })();

  // Split into executive summary and full report
  const thesis = note.thesis;
  let summary = "";
  let fullReport = thesis;

  // Try to find EXECUTIVE SUMMARY section
  const execMatch = thesis.match(/##\s*EXECUTIVE SUMMARY\s*\n([\s\S]*?)(?=\n##\s|\n---\s*\n##)/i);
  if (execMatch) {
    summary = execMatch[1].trim();
    fullReport = thesis;
  } else {
    // Fallback: use content up to the second ## heading
    const headings = [...thesis.matchAll(/\n##\s/g)];
    if (headings.length >= 2) {
      summary = thesis.slice(0, headings[1].index).trim();
    } else {
      summary = thesis.slice(0, 1500);
    }
  }

  const proseClasses = "text-sm text-terminal-text-primary leading-relaxed prose prose-invert prose-sm max-w-none prose-table:border-collapse prose-th:border prose-th:border-terminal-border prose-th:px-2 prose-th:py-1 prose-th:text-left prose-th:text-xs prose-th:font-medium prose-th:text-terminal-text-primary prose-th:bg-terminal-bg-secondary prose-td:border prose-td:border-terminal-border prose-td:px-2 prose-td:py-1 prose-td:text-xs prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-headings:text-terminal-text-primary prose-headings:mt-3 prose-headings:mb-1 prose-strong:text-terminal-text-primary prose-code:text-terminal-accent";

  return (
    <div className="mb-6 border border-terminal-border rounded bg-terminal-bg-secondary p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono font-semibold tracking-wider text-terminal-text-secondary">PORTFOLIO MANAGER</span>
          <span className="text-xs text-terminal-text-tertiary font-mono">{dateStr}</span>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-terminal-accent hover:underline font-mono"
        >
          {expanded ? "Show summary" : "Full report"}
        </button>
      </div>

      <div className={proseClasses}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {expanded ? fullReport : summary}
        </ReactMarkdown>
      </div>
    </div>
  );
}

/* ── Analyst Summaries ── */

const AGENT_LABELS: Record<string, { label: string; icon: string }> = {
  "risk-manager": { label: "Risk Manager", icon: "🛡" },
  "macro-strategist": { label: "Macro Strategist", icon: "🌍" },
  "research-analyst": { label: "Research Analyst", icon: "🔬" },
  "tax-strategist": { label: "Tax Strategist", icon: "📋" },
  "fixed-income-analyst": { label: "Fixed Income", icon: "💰" },
  "technical-analyst": { label: "Technical Analyst", icon: "📈" },
  "quant-analyst": { label: "Quant Analyst", icon: "🧮" },
  "compliance-officer": { label: "Compliance", icon: "✅" },
};

interface AnalystNote {
  id: number;
  title: string;
  thesis: string;
  tags: string[];
  createdAt: string;
}

function AnalystSummaries() {
  const [notes, setNotes] = useState<AnalystNote[]>([]);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: AnalystNote[] }>(
          "/research/notes?tag=analyst_report&limit=20"
        );
        setNotes(res.data);
      } catch { /* */ }
    })();
  }, []);

  if (notes.length === 0) return null;

  // Group by agent (second tag), keep only latest per agent
  const byAgent: Record<string, AnalystNote> = {};
  for (const n of notes) {
    const agentTag = n.tags.find((t) => t !== "analyst_report" && t !== "swarm");
    if (agentTag && !byAgent[agentTag]) {
      byAgent[agentTag] = n;
    }
  }

  const agents = Object.entries(byAgent);
  if (agents.length === 0) return null;

  // Get the date from the first note
  const reportDate = agents[0]?.[1]?.createdAt;
  const dateStr = reportDate
    ? (() => { const d = new Date(reportDate); return `${d.getDate()}.${d.getMonth()+1}.${d.getFullYear()} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; })()
    : "";

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-mono font-semibold tracking-wider text-terminal-text-secondary">ANALYST SUMMARIES</span>
        {dateStr && <span className="text-xs text-terminal-text-tertiary font-mono">{dateStr}</span>}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {agents.map(([agentTag, note]) => {
          const meta = AGENT_LABELS[agentTag] || { label: agentTag, icon: "📊" };
          const isExpanded = expandedAgent === agentTag;
          return (
            <div
              key={agentTag}
              className={`border rounded p-3 cursor-pointer transition-colors ${
                isExpanded
                  ? "border-terminal-accent bg-terminal-bg-tertiary col-span-2 md:col-span-4"
                  : "border-terminal-border bg-terminal-bg-secondary hover:border-terminal-accent/50"
              }`}
              onClick={() => setExpandedAgent(isExpanded ? null : agentTag)}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm">{meta.icon}</span>
                <span className="text-xs font-medium text-terminal-text-primary">{meta.label}</span>
              </div>
              {!isExpanded && (
                <p className="text-xs text-terminal-text-tertiary mt-1 line-clamp-2">
                  {note.thesis.slice(0, 120)}...
                </p>
              )}
              {isExpanded && (
                <div className="text-sm text-terminal-text-secondary mt-2 leading-relaxed prose prose-invert prose-sm max-w-none prose-table:border-collapse prose-th:border prose-th:border-terminal-border prose-th:px-2 prose-th:py-1 prose-th:text-left prose-th:text-xs prose-th:font-medium prose-th:text-terminal-text-primary prose-th:bg-terminal-bg-secondary prose-td:border prose-td:border-terminal-border prose-td:px-2 prose-td:py-1 prose-td:text-xs prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-headings:text-terminal-text-primary prose-headings:mt-3 prose-headings:mb-1 prose-strong:text-terminal-text-primary prose-code:text-terminal-accent">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{note.thesis}</ReactMarkdown>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Active Recommendations ── */

function ActiveTab() {
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [closing, setClosing] = useState<number | null>(null);
  const [closeNotes, setCloseNotes] = useState("");
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiGetRaw<{ data: Recommendation[]; pagination: { total: number } }>(
        "/recommendations?status=active&limit=200"
      );
      setRecs(res.data);
      setTotal(res.pagination.total);
    } catch { /* */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleClose = async (recId: number) => {
    try {
      await apiPut(`/recommendations/${recId}/close`, {
        outcome_notes: closeNotes || undefined,
      });
      setClosing(null);
      setCloseNotes("");
      load();
    } catch { /* */ }
  };

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (recs.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No active recommendations. Create one to start tracking.
        </p>
      </div>
    );
  }

  // Sort: buy/sell first, then by confidence (high > medium > low)
  const CONF_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };
  const ACTION_ORDER: Record<string, number> = { buy: 0, sell: 1, hold: 2 };
  const sorted = [...recs].sort((a, b) => {
    const aAction = ACTION_ORDER[a.action] ?? 3;
    const bAction = ACTION_ORDER[b.action] ?? 3;
    if (aAction !== bAction) return aAction - bAction;
    return (CONF_ORDER[a.confidence] ?? 3) - (CONF_ORDER[b.confidence] ?? 3);
  });

  const top5 = sorted.slice(0, 5);
  const rest = sorted.slice(5);

  const renderCard = (r: Recommendation) => (
    <div
      key={r.id}
      className="border border-terminal-border rounded bg-terminal-bg-secondary"
    >
      <div
        className="flex items-center gap-3 p-4 cursor-pointer hover:bg-terminal-bg-tertiary"
        onClick={() => setExpanded(expanded === r.id ? null : r.id)}
      >
        <span className={`text-xs px-2 py-0.5 rounded font-medium uppercase ${ACTION_COLORS[r.action] || ""}`}>
          {r.action}
        </span>
        {r.ticker && <TickerLink ticker={r.ticker} />}
        <span className="text-xs text-terminal-text-secondary">{r.securityName}</span>
        <span className={`text-xs ml-1 ${CONFIDENCE_COLORS[r.confidence] || ""}`}>
          {r.confidence}
        </span>
        {r.timeHorizon && (
          <span className="text-xs text-terminal-text-secondary">
            {HORIZON_LABELS[r.timeHorizon] || r.timeHorizon}
          </span>
        )}
        <div className="ml-auto flex items-center gap-4">
          <span className="text-xs text-terminal-text-tertiary font-mono">
            {(() => { const d = new Date(r.recommendedDate); return `${d.getDate()}.${d.getMonth()+1}.${d.getFullYear()} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; })()}
          </span>
          {r.entryPriceCents && (
            <span className="text-xs font-mono text-terminal-text-secondary">
              Entry: <Private>{formatCurrency(r.entryPriceCents, r.currency)}</Private>
            </span>
          )}
          {r.targetPriceCents && (
            <span className="text-xs font-mono text-terminal-text-secondary">
              Target: {formatCurrency(r.targetPriceCents, r.currency)}
            </span>
          )}
          {r.unrealizedReturnPct !== undefined && (
            <span className={`text-sm font-mono font-medium ${
              r.unrealizedReturnPct >= 0 ? "text-terminal-positive" : "text-terminal-negative"
            }`}>
              {formatPercent(r.unrealizedReturnPct, true)}
            </span>
          )}
        </div>
      </div>

      {expanded === r.id && (
        <div className="border-t border-terminal-border p-4 space-y-3">
          <p className="text-sm text-terminal-text-primary">{r.rationale}</p>
          {(r.bullCase || r.bearCase) && (
            <div className="grid grid-cols-2 gap-4">
              {r.bullCase && (
                <div>
                  <span className="text-xs text-terminal-positive font-medium">Bull Case</span>
                  <p className="text-xs text-terminal-text-secondary mt-1">{r.bullCase}</p>
                </div>
              )}
              {r.bearCase && (
                <div>
                  <span className="text-xs text-terminal-negative font-medium">Bear Case</span>
                  <p className="text-xs text-terminal-text-secondary mt-1">{r.bearCase}</p>
                </div>
              )}
            </div>
          )}
          <div className="flex flex-wrap gap-4 text-xs text-terminal-text-secondary">
            <span>Recommended: {formatDate(r.recommendedDate)}</span>
            {r.expiryDate && <span>Expires: {formatDate(r.expiryDate)}</span>}
            {r.source && <span>Source: {r.source}</span>}
            {r.currentPriceCents && (
              <span>Current: {formatCurrency(r.currentPriceCents, r.currency)}</span>
            )}
          </div>

          {closing === r.id ? (
            <div className="flex items-center gap-2 pt-2 border-t border-terminal-border/50">
              <input
                value={closeNotes}
                onChange={(e) => setCloseNotes(e.target.value)}
                placeholder="Outcome notes (optional)"
                className="flex-1 px-3 py-1.5 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary"
              />
              <button
                onClick={() => handleClose(r.id)}
                className="px-3 py-1.5 bg-terminal-accent text-terminal-bg-primary text-sm rounded font-medium hover:opacity-90"
              >
                Confirm Close
              </button>
              <button
                onClick={() => { setClosing(null); setCloseNotes(""); }}
                className="px-3 py-1.5 text-terminal-text-secondary text-sm hover:text-terminal-text-primary"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="pt-2 border-t border-terminal-border/50">
              <button
                onClick={(e) => { e.stopPropagation(); setClosing(r.id); }}
                className="text-xs text-terminal-text-secondary hover:text-terminal-text-primary"
              >
                Close recommendation
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );

  return (
    <div>
      <PortfolioManagerBrief />
      <AnalystSummaries />
      <p className="text-sm text-terminal-text-secondary mb-3">
        Top {Math.min(5, sorted.length)} of {total} active recommendation{total !== 1 ? "s" : ""} (sorted by priority)
      </p>
      <div className="space-y-3">
        {top5.map(renderCard)}
      </div>

      {rest.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => setShowAll(!showAll)}
            className="text-sm text-terminal-accent hover:underline font-mono"
          >
            {showAll ? "Hide" : `Show ${rest.length} more`} recommendation{rest.length !== 1 ? "s" : ""}
          </button>
          {showAll && (
            <div className="space-y-3 mt-3">
              {rest.map(renderCard)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Closed Recommendations ── */

function ClosedTab() {
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await apiGetRaw<{ data: Recommendation[]; pagination: { total: number } }>(
          "/recommendations?status=closed&limit=200"
        );
        setRecs(res.data);
        setTotal(res.pagination.total);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (recs.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">No closed recommendations yet.</p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm text-terminal-text-secondary mb-3">{total} closed recommendation{total !== 1 ? "s" : ""}</p>
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
              <th className="text-left p-3">Security</th>
              <th className="text-center p-3">Action</th>
              <th className="text-center p-3">Confidence</th>
              <th className="text-right p-3">Entry</th>
              <th className="text-right p-3">Exit</th>
              <th className="text-right p-3">Return</th>
              <th className="text-left p-3">Opened</th>
              <th className="text-left p-3">Closed</th>
              <th className="text-left p-3">Source</th>
            </tr>
          </thead>
          <tbody>
            {recs.map((r) => (
              <tr key={r.id} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
                <td className="p-3">
                  <span className="font-mono text-terminal-accent mr-2">{r.ticker}</span>
                  <span className="text-xs text-terminal-text-secondary">{r.securityName}</span>
                </td>
                <td className="text-center p-3">
                  <span className={`text-xs px-2 py-0.5 rounded uppercase ${ACTION_COLORS[r.action] || ""}`}>
                    {r.action}
                  </span>
                </td>
                <td className={`text-center p-3 text-xs capitalize ${CONFIDENCE_COLORS[r.confidence] || ""}`}>
                  {r.confidence}
                </td>
                <td className="text-right p-3 font-mono text-xs">
                  {r.entryPriceCents ? <Private>{formatCurrency(r.entryPriceCents, r.currency)}</Private> : "-"}
                </td>
                <td className="text-right p-3 font-mono text-xs">
                  {r.exitPriceCents ? <Private>{formatCurrency(r.exitPriceCents, r.currency)}</Private> : "-"}
                </td>
                <td className={`text-right p-3 font-mono text-xs font-medium ${
                  r.returnPct !== null
                    ? r.returnPct >= 0 ? "text-terminal-positive" : "text-terminal-negative"
                    : ""
                }`}>
                  {r.returnPct !== null ? formatPercent(r.returnPct, true) : "-"}
                </td>
                <td className="p-3 text-xs">{formatDate(r.recommendedDate)}</td>
                <td className="p-3 text-xs">{r.closedDate ? formatDate(r.closedDate) : "-"}</td>
                <td className="p-3 text-xs text-terminal-text-secondary">{r.source || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Retrospective ── */

function RetroTab() {
  const [data, setData] = useState<Retrospective | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: Retrospective }>("/recommendations/retrospective");
        setData(res.data);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;
  if (!data) return null;

  if (data.totalClosed === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No closed recommendations to analyze. Close some recommendations to see retrospective accuracy.
        </p>
        <p className="text-xs text-terminal-text-secondary mt-2">
          {data.activeCount} active recommendation{data.activeCount !== 1 ? "s" : ""} pending.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Closed" value={String(data.totalClosed)} />
        <MetricCard label="Active" value={String(data.activeCount)} />
        <MetricCard
          label="Hit Rate"
          value={data.hitRate !== null ? `${data.hitRate}%` : "-"}
          color={data.hitRate !== null && data.hitRate >= 50 ? "positive" : "negative"}
        />
        <MetricCard
          label="Avg Return"
          value={data.avgReturnPct !== null ? formatPercent(data.avgReturnPct, true) : "-"}
          color={data.avgReturnPct !== null && data.avgReturnPct >= 0 ? "positive" : "negative"}
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Wins" value={String(data.totalWins)} color="positive" />
        <MetricCard label="Losses" value={String(data.totalLosses)} color="negative" />
      </div>

      {/* Breakdowns */}
      <div className="grid md:grid-cols-3 gap-4">
        <BreakdownTable title="By Action" data={data.byAction} />
        <BreakdownTable title="By Confidence" data={data.byConfidence} />
        <BreakdownTable title="By Source" data={data.bySource} />
      </div>

      {/* Best / Worst */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
          <h3 className="text-sm font-medium text-terminal-positive mb-3">Best Calls</h3>
          {data.bestCalls.length === 0 ? (
            <p className="text-xs text-terminal-text-secondary">No data</p>
          ) : (
            <div className="space-y-1">
              {data.bestCalls.map((c) => (
                <div key={c.id} className="flex justify-between text-xs">
                  <span>
                    <span className={`uppercase mr-2 ${ACTION_COLORS[c.action]?.split(" ")[0] || ""}`}>{c.action}</span>
                    #{c.id}
                  </span>
                  <span className="font-mono text-terminal-positive">{formatPercent(c.returnPct, true)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
          <h3 className="text-sm font-medium text-terminal-negative mb-3">Worst Calls</h3>
          {data.worstCalls.length === 0 ? (
            <p className="text-xs text-terminal-text-secondary">No data</p>
          ) : (
            <div className="space-y-1">
              {data.worstCalls.map((c) => (
                <div key={c.id} className="flex justify-between text-xs">
                  <span>
                    <span className={`uppercase mr-2 ${ACTION_COLORS[c.action]?.split(" ")[0] || ""}`}>{c.action}</span>
                    #{c.id}
                  </span>
                  <span className="font-mono text-terminal-negative">{formatPercent(c.returnPct, true)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

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

function BreakdownTable({
  title,
  data,
}: {
  title: string;
  data: Record<string, { count: number; hitRate: number; avgReturnPct: number }>;
}) {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
        <h3 className="text-sm font-medium text-terminal-text-primary mb-2">{title}</h3>
        <p className="text-xs text-terminal-text-secondary">No data</p>
      </div>
    );
  }

  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4">
      <h3 className="text-sm font-medium text-terminal-text-primary mb-3">{title}</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-terminal-text-secondary">
            <th className="text-left pb-2"></th>
            <th className="text-right pb-2">#</th>
            <th className="text-right pb-2">Hit %</th>
            <th className="text-right pb-2">Avg Ret</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, val]) => (
            <tr key={key} className="border-t border-terminal-border/30">
              <td className="py-1.5 capitalize">{key}</td>
              <td className="text-right py-1.5 font-mono">{val.count}</td>
              <td className={`text-right py-1.5 font-mono ${val.hitRate >= 50 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                {val.hitRate}%
              </td>
              <td className={`text-right py-1.5 font-mono ${val.avgReturnPct >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                {formatPercent(val.avgReturnPct, true)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Create Recommendation ── */

function CreateTab({ onCreated }: { onCreated: () => void }) {
  const [securities, setSecurities] = useState<SecurityOption[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const [securityId, setSecurityId] = useState("");
  const [action, setAction] = useState("buy");
  const [confidence, setConfidence] = useState("medium");
  const [targetPrice, setTargetPrice] = useState("");
  const [entryPrice, setEntryPrice] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [rationale, setRationale] = useState("");
  const [bullCase, setBullCase] = useState("");
  const [bearCase, setBearCase] = useState("");
  const [source, setSource] = useState("");
  const [timeHorizon, setTimeHorizon] = useState("medium");
  const [expiryDate, setExpiryDate] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: SecurityOption[] }>("/securities?limit=500");
        setSecurities(res.data);
      } catch { /* */ }
    })();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!securityId || !rationale) {
      setError("Security and rationale are required.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await apiPost("/recommendations", {
        security_id: parseInt(securityId),
        action,
        confidence,
        target_price_cents: targetPrice ? Math.round(parseFloat(targetPrice) * 100) : undefined,
        entry_price_cents: entryPrice ? Math.round(parseFloat(entryPrice) * 100) : undefined,
        currency,
        rationale,
        bull_case: bullCase || undefined,
        bear_case: bearCase || undefined,
        source: source || undefined,
        time_horizon: timeHorizon || undefined,
        expiry_date: expiryDate || undefined,
      });
      onCreated();
    } catch {
      setError("Failed to create recommendation.");
    }
    setSubmitting(false);
  };

  const inputCls = "w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary focus:border-terminal-accent focus:outline-none";
  const labelCls = "block text-xs text-terminal-text-secondary mb-1";

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl space-y-4">
      {error && (
        <div className="text-sm text-terminal-negative bg-terminal-negative/10 px-3 py-2 rounded">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Security *</label>
          <select value={securityId} onChange={(e) => setSecurityId(e.target.value)} className={inputCls}>
            <option value="">Select security...</option>
            {securities.map((s) => (
              <option key={s.id} value={s.id}>
                {s.ticker} — {s.name}
              </option>
            ))}
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
          <label className={labelCls}>Action *</label>
          <select value={action} onChange={(e) => setAction(e.target.value)} className={inputCls}>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
            <option value="hold">Hold</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Confidence *</label>
          <select value={confidence} onChange={(e) => setConfidence(e.target.value)} className={inputCls}>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Time Horizon</label>
          <select value={timeHorizon} onChange={(e) => setTimeHorizon(e.target.value)} className={inputCls}>
            <option value="short">Short (&lt; 3m)</option>
            <option value="medium">Medium (3-12m)</option>
            <option value="long">Long (&gt; 12m)</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Entry Price (auto-filled if empty)</label>
          <input
            type="number"
            step="0.01"
            value={entryPrice}
            onChange={(e) => setEntryPrice(e.target.value)}
            placeholder="e.g. 45.50"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>Target Price</label>
          <input
            type="number"
            step="0.01"
            value={targetPrice}
            onChange={(e) => setTargetPrice(e.target.value)}
            placeholder="e.g. 55.00"
            className={inputCls}
          />
        </div>
      </div>

      <div>
        <label className={labelCls}>Rationale *</label>
        <textarea
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          rows={3}
          placeholder="Why this recommendation?"
          className={inputCls}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Bull Case</label>
          <textarea
            value={bullCase}
            onChange={(e) => setBullCase(e.target.value)}
            rows={2}
            placeholder="Best case scenario"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>Bear Case</label>
          <textarea
            value={bearCase}
            onChange={(e) => setBearCase(e.target.value)}
            rows={2}
            placeholder="Worst case scenario"
            className={inputCls}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Source</label>
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="e.g. research-analyst, manual"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>Expiry Date</label>
          <input
            type="date"
            value={expiryDate}
            onChange={(e) => setExpiryDate(e.target.value)}
            className={inputCls}
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="px-6 py-2 bg-terminal-accent text-terminal-bg-primary rounded font-medium text-sm hover:opacity-90 disabled:opacity-50"
      >
        {submitting ? "Creating..." : "Create Recommendation"}
      </button>
    </form>
  );
}
