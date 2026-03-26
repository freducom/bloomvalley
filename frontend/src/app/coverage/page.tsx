"use client";

import { useEffect, useState } from "react";
import { apiGetRaw } from "@/lib/api";
import { TickerLink } from "@/components/ui/TickerLink";

interface CoverageItem {
  securityId: number;
  ticker: string;
  name: string;
  assetClass: string;
  isInPortfolio: boolean;
  isOnWatchlist: boolean;
  lastResearchDate: string | null;
  noteCount: number;
  hasAnalystNote: boolean;
  hasTechnicalNote: boolean;
  staleness: "fresh" | "stale" | "very_stale" | "missing";
}

interface CoverageSummary {
  total: number;
  fresh: number;
  stale: number;
  veryStale: number;
  missing: number;
}

const STALENESS_STYLE: Record<string, { label: string; cls: string }> = {
  fresh: { label: "Fresh", cls: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40" },
  stale: { label: "Stale", cls: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40" },
  very_stale: { label: "Very Stale", cls: "bg-red-500/20 text-red-400 border-red-500/40" },
  missing: { label: "Missing", cls: "bg-zinc-500/20 text-zinc-400 border-zinc-500/40" },
};

export default function CoveragePage() {
  const [items, setItems] = useState<CoverageItem[]>([]);
  const [summary, setSummary] = useState<CoverageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    apiGetRaw<{ data: CoverageItem[]; summary: CoverageSummary }>("/research/coverage")
      .then((res) => {
        setItems(res.data || []);
        setSummary(res.summary || null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = items.filter((i) => {
    if (filter === "portfolio") return i.isInPortfolio;
    if (filter === "watchlist") return i.isOnWatchlist && !i.isInPortfolio;
    if (filter === "stale") return i.staleness === "stale" || i.staleness === "very_stale";
    if (filter === "missing") return i.staleness === "missing";
    return true;
  });

  if (loading) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-bold text-terminal-text-primary mb-4">Research Coverage</h1>
        <div className="text-sm text-terminal-text-muted animate-pulse">Loading coverage data...</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl">
      <h1 className="text-lg font-bold text-terminal-text-primary mb-4">Research Coverage</h1>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-3 text-center">
            <div className="text-2xl font-bold text-terminal-text-primary">{summary.total}</div>
            <div className="text-xs text-terminal-text-muted">Total</div>
          </div>
          <div className="bg-terminal-bg-secondary border border-emerald-500/30 rounded p-3 text-center">
            <div className="text-2xl font-bold text-emerald-400">{summary.fresh}</div>
            <div className="text-xs text-terminal-text-muted">Fresh (&lt;3d)</div>
          </div>
          <div className="bg-terminal-bg-secondary border border-yellow-500/30 rounded p-3 text-center">
            <div className="text-2xl font-bold text-yellow-400">{summary.stale}</div>
            <div className="text-xs text-terminal-text-muted">Stale (3-7d)</div>
          </div>
          <div className="bg-terminal-bg-secondary border border-red-500/30 rounded p-3 text-center">
            <div className="text-2xl font-bold text-red-400">{summary.veryStale}</div>
            <div className="text-xs text-terminal-text-muted">Very Stale (&gt;7d)</div>
          </div>
          <div className="bg-terminal-bg-secondary border border-zinc-500/30 rounded p-3 text-center">
            <div className="text-2xl font-bold text-zinc-400">{summary.missing}</div>
            <div className="text-xs text-terminal-text-muted">Missing</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {[
          { value: "all", label: "All" },
          { value: "portfolio", label: "Portfolio" },
          { value: "watchlist", label: "Watchlist Only" },
          { value: "stale", label: "Stale" },
          { value: "missing", label: "Missing" },
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
              <th className="text-center p-2">Type</th>
              <th className="text-center p-2">Source</th>
              <th className="text-center p-2">Analyst</th>
              <th className="text-center p-2">Technical</th>
              <th className="text-center p-2">Notes</th>
              <th className="text-left p-2">Last Research</th>
              <th className="text-center p-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => {
              const s = STALENESS_STYLE[item.staleness] || STALENESS_STYLE.missing;
              const age = item.lastResearchDate
                ? Math.floor((Date.now() - new Date(item.lastResearchDate).getTime()) / 86400000)
                : null;
              return (
                <tr key={item.securityId} className="border-b border-terminal-border/50 hover:bg-terminal-bg-hover">
                  <td className="p-2">
                    <TickerLink ticker={item.ticker} className="font-mono text-terminal-accent hover:underline" />
                    <span className="ml-2 text-terminal-text-muted text-xs">{item.name}</span>
                  </td>
                  <td className="p-2 text-center text-xs text-terminal-text-muted">{item.assetClass}</td>
                  <td className="p-2 text-center">
                    {item.isInPortfolio && <span className="text-xs bg-blue-500/20 text-blue-400 border border-blue-500/40 rounded px-1.5 py-0.5 mr-1">Held</span>}
                    {item.isOnWatchlist && <span className="text-xs bg-purple-500/20 text-purple-400 border border-purple-500/40 rounded px-1.5 py-0.5">WL</span>}
                  </td>
                  <td className="p-2 text-center">
                    {item.hasAnalystNote ? <span className="text-emerald-400">Y</span> : <span className="text-zinc-500">-</span>}
                  </td>
                  <td className="p-2 text-center">
                    {item.hasTechnicalNote ? <span className="text-emerald-400">Y</span> : <span className="text-zinc-500">-</span>}
                  </td>
                  <td className="p-2 text-center text-terminal-text-muted">{item.noteCount}</td>
                  <td className="p-2 text-xs text-terminal-text-muted">
                    {item.lastResearchDate
                      ? `${new Date(item.lastResearchDate).toLocaleDateString("fi-FI")} (${age}d ago)`
                      : "Never"}
                  </td>
                  <td className="p-2 text-center">
                    <span className={`text-xs px-2 py-0.5 rounded border ${s.cls}`}>{s.label}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <p className="text-center text-terminal-text-muted text-sm py-8">No securities match the selected filter.</p>
        )}
      </div>
    </div>
  );
}
