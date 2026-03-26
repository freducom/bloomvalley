"use client";

import { useEffect, useState } from "react";
import { apiGetRaw, apiPost } from "@/lib/api";
import { TickerLink } from "@/components/ui/TickerLink";

interface CheckpointStats {
  total: number;
  wins: number;
  winRate: number | null;
  avgReturn: number | null;
}

interface CallEntry {
  ticker: string;
  action: string;
  daysElapsed: number;
  returnPct: number;
  recommendedDate: string;
}

interface AccuracyData {
  checkpoints: Record<string, CheckpointStats>;
  byAction: Record<string, Record<string, CheckpointStats>>;
  bestCalls: CallEntry[];
  worstCalls: CallEntry[];
}

const HORIZON_LABELS: Record<string, string> = {
  "30d": "30 Days",
  "90d": "90 Days",
  "180d": "180 Days",
};

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-3">
      <div className="text-xs text-terminal-text-muted mb-1">{label}</div>
      <div className={`text-xl font-bold ${color || "text-terminal-text-primary"}`}>{value}</div>
      {sub && <div className="text-xs text-terminal-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export default function AccuracyPage() {
  const [data, setData] = useState<AccuracyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [computing, setComputing] = useState(false);

  const load = () => {
    setLoading(true);
    apiGetRaw<{ data: AccuracyData }>("/recommendations/accuracy")
      .then((res) => setData(res.data || null))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const computeCheckpoints = () => {
    setComputing(true);
    apiPost<{ data: { created: number } }>("/recommendations/compute-checkpoints")
      .then(() => load())
      .catch(() => {})
      .finally(() => setComputing(false));
  };

  if (loading) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-bold text-terminal-text-primary mb-4">Recommendation Accuracy</h1>
        <div className="text-sm text-terminal-text-muted animate-pulse">Loading accuracy data...</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-lg font-bold text-terminal-text-primary">Recommendation Accuracy</h1>
          <p className="text-xs text-terminal-text-muted">
            Mark-to-market performance of PM recommendations at 30, 90, and 180 day checkpoints.
          </p>
        </div>
        <button
          onClick={computeCheckpoints}
          disabled={computing}
          className="px-3 py-1.5 text-xs rounded border bg-terminal-accent/20 text-terminal-accent border-terminal-accent/40 hover:bg-terminal-accent/30 disabled:opacity-50"
        >
          {computing ? "Computing..." : "Update Checkpoints"}
        </button>
      </div>

      {!data || !data.checkpoints || Object.keys(data.checkpoints).length === 0 ? (
        <div className="text-center py-12 text-terminal-text-muted">
          <p className="text-sm mb-2">No checkpoint data yet.</p>
          <p className="text-xs">Click &ldquo;Update Checkpoints&rdquo; to compute accuracy from historical recommendations and prices.</p>
        </div>
      ) : (
        <>
          {/* Overall accuracy by time horizon */}
          <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">Overall Accuracy</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            {Object.entries(HORIZON_LABELS).map(([key, label]) => {
              const cp = data.checkpoints[key];
              if (!cp) return null;
              const winColor = cp.winRate !== null
                ? cp.winRate >= 60 ? "text-emerald-400" : cp.winRate >= 40 ? "text-yellow-400" : "text-red-400"
                : "text-terminal-text-muted";
              const retColor = cp.avgReturn !== null
                ? cp.avgReturn > 0 ? "text-emerald-400" : "text-red-400"
                : "text-terminal-text-muted";
              return (
                <div key={key} className="bg-terminal-bg-secondary border border-terminal-border rounded p-4">
                  <h3 className="text-xs text-terminal-text-muted mb-3 font-medium">{label}</h3>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <div className={`text-2xl font-bold ${winColor}`}>
                        {cp.winRate !== null ? `${cp.winRate}%` : "-"}
                      </div>
                      <div className="text-[10px] text-terminal-text-muted">Win Rate</div>
                    </div>
                    <div>
                      <div className={`text-2xl font-bold ${retColor}`}>
                        {cp.avgReturn !== null ? `${cp.avgReturn > 0 ? "+" : ""}${cp.avgReturn}%` : "-"}
                      </div>
                      <div className="text-[10px] text-terminal-text-muted">Avg Return</div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold text-terminal-text-primary">{cp.total}</div>
                      <div className="text-[10px] text-terminal-text-muted">Sample</div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* By action breakdown */}
          {data.byAction && Object.keys(data.byAction).length > 0 && (
            <>
              <h2 className="text-sm font-semibold text-terminal-text-secondary mb-3">By Action</h2>
              <div className="overflow-x-auto mb-6">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-terminal-border text-terminal-text-muted text-xs">
                      <th className="text-left p-2">Action</th>
                      {Object.keys(HORIZON_LABELS).map((h) => (
                        <th key={h} className="text-center p-2" colSpan={2}>{HORIZON_LABELS[h]}</th>
                      ))}
                    </tr>
                    <tr className="border-b border-terminal-border text-terminal-text-muted text-[10px]">
                      <th />
                      {Object.keys(HORIZON_LABELS).map((h) => (
                        <>
                          <th key={`${h}-wr`} className="text-center p-1">Win Rate</th>
                          <th key={`${h}-ar`} className="text-center p-1">Avg Ret</th>
                        </>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.byAction).map(([action, horizons]) => (
                      <tr key={action} className="border-b border-terminal-border/50">
                        <td className="p-2 font-medium capitalize">{action}</td>
                        {Object.keys(HORIZON_LABELS).map((h) => {
                          const cp = horizons[h];
                          return (
                            <>
                              <td key={`${h}-wr`} className="p-2 text-center text-xs">
                                {cp?.winRate !== null && cp?.winRate !== undefined ? `${cp.winRate}%` : "-"}
                              </td>
                              <td key={`${h}-ar`} className={`p-2 text-center text-xs ${cp?.avgReturn && cp.avgReturn > 0 ? "text-emerald-400" : cp?.avgReturn && cp.avgReturn < 0 ? "text-red-400" : ""}`}>
                                {cp?.avgReturn !== null && cp?.avgReturn !== undefined ? `${cp.avgReturn > 0 ? "+" : ""}${cp.avgReturn}%` : "-"}
                              </td>
                            </>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Best & Worst calls */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {data.bestCalls && data.bestCalls.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-emerald-400 mb-3">Best Calls</h2>
                <div className="space-y-1">
                  {data.bestCalls.map((c, i) => (
                    <div key={i} className="flex items-center justify-between bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-2">
                      <div className="flex items-center gap-2">
                        <TickerLink ticker={c.ticker} className="font-mono text-terminal-accent text-sm hover:underline" />
                        <span className="text-[10px] text-terminal-text-muted capitalize">{c.action}</span>
                        <span className="text-[10px] text-terminal-text-muted">{c.daysElapsed}d</span>
                      </div>
                      <span className="text-sm font-bold text-emerald-400">+{c.returnPct.toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {data.worstCalls && data.worstCalls.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-red-400 mb-3">Worst Calls</h2>
                <div className="space-y-1">
                  {data.worstCalls.map((c, i) => (
                    <div key={i} className="flex items-center justify-between bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-2">
                      <div className="flex items-center gap-2">
                        <TickerLink ticker={c.ticker} className="font-mono text-terminal-accent text-sm hover:underline" />
                        <span className="text-[10px] text-terminal-text-muted capitalize">{c.action}</span>
                        <span className="text-[10px] text-terminal-text-muted">{c.daysElapsed}d</span>
                      </div>
                      <span className="text-sm font-bold text-red-400">{c.returnPct.toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
