"use client";

import { useEffect, useState } from "react";
import { apiGetRaw } from "@/lib/api";
import { TickerLink } from "@/components/ui/TickerLink";

interface AgentInfo {
  hasNote: boolean;
  verdict: string | null;
  updatedAt: string | null;
}

interface ConsensusItem {
  securityId: number;
  ticker: string;
  name: string;
  pmAction: string | null;
  pmConfidence: string | null;
  researchVerdict: string | null;
  moatRating: string | null;
  agentCoverage: number;
  totalAgents: number;
  hasConflict: boolean;
  conflictDetails: string | null;
  agents: Record<string, AgentInfo>;
}

const AGENT_NAMES = [
  "research-analyst",
  "technical-analyst",
  "risk-manager",
  "quant-analyst",
  "macro-strategist",
  "fixed-income-analyst",
  "tax-strategist",
  "compliance-officer",
  "portfolio-manager",
];

const AGENT_SHORT: Record<string, string> = {
  "research-analyst": "Research",
  "technical-analyst": "Technical",
  "risk-manager": "Risk",
  "quant-analyst": "Quant",
  "macro-strategist": "Macro",
  "fixed-income-analyst": "Fixed Inc",
  "tax-strategist": "Tax",
  "compliance-officer": "Compliance",
  "portfolio-manager": "PM",
};

const ACTION_STYLE: Record<string, string> = {
  buy: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  sell: "bg-red-500/20 text-red-400 border-red-500/40",
  hold: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  BUY: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  ACCUMULATE: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
  SELL: "bg-red-500/20 text-red-400 border-red-500/40",
  AVOID: "bg-red-500/20 text-red-400 border-red-500/40",
  TRIM: "bg-red-500/20 text-red-400 border-red-500/40",
  HOLD: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  WAIT: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
};

const MOAT_STYLE: Record<string, string> = {
  wide: "text-emerald-400",
  narrow: "text-yellow-400",
  none: "text-red-400",
};

export default function ConsensusPage() {
  const [items, setItems] = useState<ConsensusItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    apiGetRaw<{ data: ConsensusItem[] }>("/research/consensus")
      .then((res) => setItems(res.data || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const conflicts = items.filter((i) => i.hasConflict).length;

  const filtered = items.filter((i) => {
    if (filter === "conflicts") return i.hasConflict;
    if (filter === "low-coverage") return i.agentCoverage < 3;
    return true;
  });

  if (loading) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-bold text-terminal-text-primary mb-4">Analyst Consensus</h1>
        <div className="text-sm text-terminal-text-muted animate-pulse">Loading consensus data...</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl">
      <h1 className="text-lg font-bold text-terminal-text-primary mb-2">Analyst Consensus</h1>
      <p className="text-xs text-terminal-text-muted mb-4">
        How the 9 AI analysts agree or disagree on each security. Conflicts are flagged when the Research Analyst
        and Portfolio Manager disagree.
      </p>

      {/* Summary */}
      <div className="flex gap-4 mb-4">
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded px-4 py-2">
          <span className="text-xl font-bold text-terminal-text-primary">{items.length}</span>
          <span className="text-xs text-terminal-text-muted ml-2">Securities</span>
        </div>
        {conflicts > 0 && (
          <div className="bg-red-500/10 border border-red-500/30 rounded px-4 py-2">
            <span className="text-xl font-bold text-red-400">{conflicts}</span>
            <span className="text-xs text-red-400/70 ml-2">Conflicts</span>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-4">
        {[
          { value: "all", label: "All" },
          { value: "conflicts", label: `Conflicts (${conflicts})` },
          { value: "low-coverage", label: "Low Coverage (<3 agents)" },
        ].map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`px-3 py-1 text-xs rounded border transition-colors ${
              filter === f.value
                ? "bg-terminal-accent/20 text-terminal-accent border-terminal-accent/40"
                : "bg-terminal-bg-secondary text-terminal-text-secondary border-terminal-border hover:border-terminal-text-muted"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-terminal-border text-terminal-text-muted text-xs">
              <th className="text-left p-2">Security</th>
              <th className="text-center p-2">PM Action</th>
              <th className="text-center p-2">Research Verdict</th>
              <th className="text-center p-2">Moat</th>
              <th className="text-center p-2">Coverage</th>
              <th className="text-center p-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => (
              <>
                <tr
                  key={item.securityId}
                  className={`border-b border-terminal-border/50 hover:bg-terminal-bg-hover cursor-pointer ${
                    item.hasConflict ? "bg-red-500/5" : ""
                  }`}
                  onClick={() => setExpanded(expanded === item.securityId ? null : item.securityId)}
                >
                  <td className="p-2">
                    <TickerLink ticker={item.ticker} className="font-mono text-terminal-accent hover:underline" />
                    <span className="ml-2 text-terminal-text-muted text-xs">{item.name}</span>
                  </td>
                  <td className="p-2 text-center">
                    {item.pmAction ? (
                      <span className={`text-xs px-2 py-0.5 rounded border ${ACTION_STYLE[item.pmAction] || "text-terminal-text-muted"}`}>
                        {item.pmAction.toUpperCase()}
                      </span>
                    ) : (
                      <span className="text-xs text-zinc-500">-</span>
                    )}
                  </td>
                  <td className="p-2 text-center">
                    {item.researchVerdict ? (
                      <span className={`text-xs px-2 py-0.5 rounded border ${ACTION_STYLE[item.researchVerdict] || "text-terminal-text-muted"}`}>
                        {item.researchVerdict}
                      </span>
                    ) : (
                      <span className="text-xs text-zinc-500">-</span>
                    )}
                  </td>
                  <td className="p-2 text-center">
                    {item.moatRating ? (
                      <span className={`text-xs font-medium ${MOAT_STYLE[item.moatRating] || "text-terminal-text-muted"}`}>
                        {item.moatRating}
                      </span>
                    ) : (
                      <span className="text-xs text-zinc-500">-</span>
                    )}
                  </td>
                  <td className="p-2 text-center">
                    <span className={`text-xs ${item.agentCoverage < 3 ? "text-red-400" : "text-terminal-text-muted"}`}>
                      {item.agentCoverage}/{item.totalAgents}
                    </span>
                  </td>
                  <td className="p-2 text-center">
                    {item.hasConflict ? (
                      <span className="text-xs px-2 py-0.5 rounded border bg-red-500/20 text-red-400 border-red-500/40">
                        Conflict
                      </span>
                    ) : (
                      <span className="text-xs text-emerald-400">Aligned</span>
                    )}
                  </td>
                </tr>
                {expanded === item.securityId && (
                  <tr key={`${item.securityId}-detail`} className="border-b border-terminal-border/50">
                    <td colSpan={6} className="p-3 bg-terminal-bg-secondary">
                      {item.conflictDetails && (
                        <div className="mb-3 px-3 py-2 rounded border bg-red-500/10 border-red-500/30 text-xs text-red-400">
                          {item.conflictDetails}
                        </div>
                      )}
                      <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-2">
                        {AGENT_NAMES.map((agent) => {
                          const info = item.agents[agent];
                          return (
                            <div
                              key={agent}
                              className={`rounded border p-2 text-center ${
                                info?.hasNote
                                  ? "border-terminal-border bg-terminal-bg-primary"
                                  : "border-terminal-border/30 bg-terminal-bg-secondary opacity-40"
                              }`}
                            >
                              <div className="text-[10px] text-terminal-text-muted mb-1">{AGENT_SHORT[agent]}</div>
                              {info?.hasNote ? (
                                <>
                                  {info.verdict && (
                                    <span className={`text-[10px] px-1 py-0.5 rounded ${ACTION_STYLE[info.verdict] || "text-terminal-text-muted"}`}>
                                      {info.verdict}
                                    </span>
                                  )}
                                  {!info.verdict && <span className="text-xs text-emerald-400">Y</span>}
                                </>
                              ) : (
                                <span className="text-xs text-zinc-500">-</span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <p className="text-center text-terminal-text-muted text-sm py-8">No securities match the selected filter.</p>
        )}
      </div>
    </div>
  );
}
