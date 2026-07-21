"use client";

import { useEffect, useState } from "react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  ReferenceArea,
} from "recharts";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

async function fetchRrg(): Promise<{ data: RrgPayload }> {
  const res = await fetch(`${API_BASE}/api/v1/rrg`, { cache: "no-store" });
  const json = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = json?.detail;
    const msg = detail?.message || detail?.error || `API error: ${res.status}`;
    const err = new Error(msg) as Error & { detail?: unknown };
    err.detail = detail;
    throw err;
  }
  return json as { data: RrgPayload };
}
import { InfoTip } from "@/components/ui/InfoTip";
import { TickerLink } from "@/components/ui/TickerLink";

type Quadrant = "Leading" | "Weakening" | "Lagging" | "Improving";
type Signal = "buy" | "sell" | "moved" | null;

interface TailPoint {
  date: string;
  rsRatio: number;
  rsMomentum: number;
}

interface TopEtf {
  securityId: number;
  ticker: string;
  name: string;
  avgDollarVolume: number | null;
}

interface TopStock {
  securityId: number;
  ticker: string;
  name: string;
  marketCapCents: number | null;
}

interface SectorRow {
  sector: string;
  ticker: string;
  name: string;
  rsRatio: number;
  rsMomentum: number;
  quadrant: Quadrant;
  quadrant4wAgo: Quadrant | null;
  signal: Signal;
  tail: TailPoint[];
  topEtfs?: TopEtf[];
  topStocks?: TopStock[];
}

interface RrgPayload {
  asOf: string | null;
  benchmark: { ticker: string; name: string };
  sectors: SectorRow[];
  insufficientHistory: string[];
  error?: string;
  message?: string;
  missing?: string[];
}

const QUADRANT_COLOR: Record<Quadrant, string> = {
  Leading: "#16a34a", // green
  Weakening: "#eab308", // yellow
  Lagging: "#ef4444", // red
  Improving: "#3b82f6", // blue
};

const SIGNAL_STYLE: Record<Exclude<Signal, null>, { label: string; cls: string }> = {
  buy: { label: "BUY", cls: "bg-terminal-positive/20 text-terminal-positive border-terminal-positive/40" },
  sell: { label: "SELL", cls: "bg-terminal-negative/20 text-terminal-negative border-terminal-negative/40" },
  moved: { label: "MOVED", cls: "bg-terminal-warning/20 text-terminal-warning border-terminal-warning/40" },
};

function fmtMarketCap(cents: number | null): string {
  if (!cents) return "—";
  const usd = cents / 100;
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(2)}T`;
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(2)}M`;
  return `$${usd.toFixed(0)}`;
}

function fmtDollarVol(dv: number | null): string {
  if (!dv) return "—";
  if (dv >= 1e9) return `$${(dv / 1e9).toFixed(2)}B/day`;
  if (dv >= 1e6) return `$${(dv / 1e6).toFixed(1)}M/day`;
  if (dv >= 1e3) return `$${(dv / 1e3).toFixed(0)}K/day`;
  return `$${dv.toFixed(0)}/day`;
}

function SectorLabel({ cx, cy, payload }: { cx?: number; cy?: number; payload?: { ticker: string; quadrant: Quadrant } }) {
  if (cx == null || cy == null || !payload) return null;
  return (
    <g>
      <circle cx={cx} cy={cy} r={6} fill={QUADRANT_COLOR[payload.quadrant]} stroke="#0a0a0a" strokeWidth={1.5} />
      <text x={cx + 9} y={cy + 3} fontSize={11} fontFamily="ui-monospace, monospace" fill="#e5e5e5">
        {payload.ticker}
      </text>
    </g>
  );
}

function TailDot({ cx, cy, payload }: { cx?: number; cy?: number; payload?: { quadrant: Quadrant; isCurrent?: boolean } }) {
  if (cx == null || cy == null || !payload) return null;
  const r = payload.isCurrent ? 5 : 2.5;
  const color = QUADRANT_COLOR[payload.quadrant] ?? "#888";
  return <circle cx={cx} cy={cy} r={r} fill={color} opacity={payload.isCurrent ? 1 : 0.55} />;
}

interface CurrentDatum {
  x: number;
  y: number;
  ticker: string;
  sector: string;
  quadrant: Quadrant;
  signal: Signal;
}

interface TailDatum {
  x: number;
  y: number;
  ticker: string;
  quadrant: Quadrant;
  isCurrent: boolean;
}

const QUADRANT_INFO: Record<Quadrant, string> = {
  Leading: "Outperforming SPY with positive momentum. Trend followers stay long here.",
  Weakening: "Still outperforming SPY but momentum has turned down. Watch for the RS-Ratio to fall below 100.",
  Lagging: "Underperforming SPY with negative momentum. Avoid or short.",
  Improving: "Underperforming SPY but momentum has turned up. Watch for RS-Ratio to cross 100 into Leading.",
};

export default function RrgPage() {
  const [data, setData] = useState<RrgPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchRrg()
      .then((res) => setData(res.data || null))
      .catch((e) => setError(String(e?.message || e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-bold text-terminal-text-primary mb-4">Sector Rotation</h1>
        <div className="text-sm text-terminal-text-muted animate-pulse">Loading RRG…</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-6 max-w-4xl">
        <h1 className="text-lg font-bold text-terminal-text-primary mb-4">Sector Rotation</h1>
        <div className="bg-terminal-negative/10 border border-terminal-negative/40 text-terminal-negative text-sm rounded p-4">
          <div className="font-semibold mb-1">Unable to compute RRG</div>
          <div className="text-xs">
            {error ||
              "The endpoint returned no data. Ensure SPY and the 11 SPDR sector ETFs are seeded and that the yahoo_daily_prices pipeline has been run."}
          </div>
        </div>
      </div>
    );
  }

  const sectors = data.sectors || [];
  const currentPoints: CurrentDatum[] = sectors.map((s) => ({
    x: s.rsRatio,
    y: s.rsMomentum,
    ticker: s.ticker,
    sector: s.sector,
    quadrant: s.quadrant,
    signal: s.signal,
  }));

  // Chart bounds — expand slightly around min/max so labels fit
  const allX = sectors.flatMap((s) => [s.rsRatio, ...s.tail.map((t) => t.rsRatio)]);
  const allY = sectors.flatMap((s) => [s.rsMomentum, ...s.tail.map((t) => t.rsMomentum)]);
  const pad = 0.6;
  const spread = (vals: number[]) => {
    if (!vals.length) return [98, 102] as [number, number];
    const lo = Math.min(...vals, 99);
    const hi = Math.max(...vals, 101);
    const range = Math.max(2, hi - lo);
    return [lo - range * 0.15 - pad, hi + range * 0.15 + pad] as [number, number];
  };
  const [xMin, xMax] = spread(allX);
  const [yMin, yMax] = spread(allY);

  const signalCounts = sectors.reduce(
    (acc, s) => {
      if (s.signal === "buy") acc.buy++;
      else if (s.signal === "sell") acc.sell++;
      else if (s.signal === "moved") acc.moved++;
      return acc;
    },
    { buy: 0, sell: 0, moved: 0 },
  );

  const movers = sectors.filter((s) => s.signal !== null);

  return (
    <div className="p-6 max-w-7xl">
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h1 className="text-lg font-bold text-terminal-text-primary flex items-center gap-2">
            Sector Rotation
            <InfoTip text="Relative Rotation Graph (RRG). A 4-quadrant chart that plots each S&P 500 sector by its Relative Strength vs SPY (X axis) and the rate of change of that strength (Y axis). Sectors rotate clockwise: Improving → Leading → Weakening → Lagging → Improving." />
          </h1>
          <p className="text-xs text-terminal-text-muted mt-1">
            14-week Relative Rotation Graph of the 11 GICS sectors vs {data.benchmark.ticker}.
            {data.asOf ? ` As of ${data.asOf}.` : ""}
          </p>
        </div>
        <button
          onClick={load}
          className="px-3 py-1.5 text-xs rounded border bg-terminal-accent/20 text-terminal-accent border-terminal-accent/40 hover:bg-terminal-accent/30"
        >
          Refresh
        </button>
      </div>

      {/* Signal summary */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-3">
          <div className="text-xs text-terminal-text-muted flex items-center gap-1">
            Buy signals
            <InfoTip text="Sectors that crossed from Improving to Leading over the last 4 weeks — RS-Ratio rose above 100 while momentum stayed above 100. Classic rotation-into-leadership setup." />
          </div>
          <div className="text-2xl font-bold text-terminal-positive">{signalCounts.buy}</div>
        </div>
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-3">
          <div className="text-xs text-terminal-text-muted flex items-center gap-1">
            Sell signals
            <InfoTip text="Sectors that crossed from Weakening to Lagging over the last 4 weeks — RS-Ratio fell below 100 with momentum already below 100. Rotation-out-of-leadership setup." />
          </div>
          <div className="text-2xl font-bold text-terminal-negative">{signalCounts.sell}</div>
        </div>
        <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-3">
          <div className="text-xs text-terminal-text-muted flex items-center gap-1">
            Other quadrant moves
            <InfoTip text="Sectors that changed quadrants but didn't trigger a full buy/sell signal (e.g., Leading → Weakening)." />
          </div>
          <div className="text-2xl font-bold text-terminal-warning">{signalCounts.moved}</div>
        </div>
      </div>

      {/* Chart */}
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-4 mb-6">
        <div className="flex items-center gap-4 text-xs text-terminal-text-muted mb-2">
          <span className="flex items-center gap-1">
            X = RS-Ratio
            <InfoTip text="Relative Strength Ratio: 100 × (sector / SPY) divided by the 14-week SMA of that ratio. Above 100 means the sector is outperforming SPY on this window; below 100 means it's underperforming." />
          </span>
          <span className="flex items-center gap-1">
            Y = RS-Momentum
            <InfoTip text="Rate of change of RS-Ratio: 100 × RS-Ratio divided by the 14-week SMA of RS-Ratio. Above 100 means relative strength is accelerating; below 100 means it's decelerating." />
          </span>
          <span className="ml-auto">Tail: last 4 weekly points • dot = current week</span>
        </div>

        <div style={{ width: "100%", height: 480 }}>
          <ResponsiveContainer>
            <ScatterChart margin={{ top: 20, right: 40, bottom: 40, left: 40 }}>
              <CartesianGrid stroke="#222" strokeDasharray="3 3" />

              {/* Quadrant background tints */}
              <ReferenceArea x1={100} x2={xMax} y1={100} y2={yMax} fill={QUADRANT_COLOR.Leading} fillOpacity={0.06} />
              <ReferenceArea x1={100} x2={xMax} y1={yMin} y2={100} fill={QUADRANT_COLOR.Weakening} fillOpacity={0.06} />
              <ReferenceArea x1={xMin} x2={100} y1={yMin} y2={100} fill={QUADRANT_COLOR.Lagging} fillOpacity={0.06} />
              <ReferenceArea x1={xMin} x2={100} y1={100} y2={yMax} fill={QUADRANT_COLOR.Improving} fillOpacity={0.06} />

              <ReferenceLine x={100} stroke="#666" strokeDasharray="4 4" />
              <ReferenceLine y={100} stroke="#666" strokeDasharray="4 4" />

              <XAxis
                type="number"
                dataKey="x"
                domain={[xMin, xMax]}
                label={{ value: "RS-Ratio", position: "insideBottom", offset: -10, fill: "#888", fontSize: 11 }}
                tick={{ fill: "#888", fontSize: 10 }}
                stroke="#444"
              />
              <YAxis
                type="number"
                dataKey="y"
                domain={[yMin, yMax]}
                label={{ value: "RS-Momentum", angle: -90, position: "insideLeft", fill: "#888", fontSize: 11 }}
                tick={{ fill: "#888", fontSize: 10 }}
                stroke="#444"
              />
              <ZAxis range={[60, 60]} />
              <Tooltip
                cursor={{ strokeDasharray: "3 3" }}
                content={({ active, payload }) => {
                  if (!active || !payload || !payload.length) return null;
                  const p = payload[0].payload as CurrentDatum | TailDatum;
                  return (
                    <div className="bg-terminal-bg-tertiary border border-terminal-border rounded p-2 text-xs">
                      <div className="font-mono font-bold text-terminal-text-primary">{p.ticker}</div>
                      {"sector" in p && <div className="text-terminal-text-muted">{p.sector}</div>}
                      <div>RS-Ratio: {p.x.toFixed(2)}</div>
                      <div>RS-Momentum: {p.y.toFixed(2)}</div>
                      <div>Quadrant: <span style={{ color: QUADRANT_COLOR[p.quadrant] }}>{p.quadrant}</span></div>
                    </div>
                  );
                }}
              />

              {/* Quadrant corner labels */}
              <text x="98%" y="8%" textAnchor="end" fill={QUADRANT_COLOR.Leading} fontSize={11} fontWeight="bold">LEADING</text>
              <text x="98%" y="97%" textAnchor="end" fill={QUADRANT_COLOR.Weakening} fontSize={11} fontWeight="bold">WEAKENING</text>
              <text x="2%" y="97%" textAnchor="start" fill={QUADRANT_COLOR.Lagging} fontSize={11} fontWeight="bold">LAGGING</text>
              <text x="2%" y="8%" textAnchor="start" fill={QUADRANT_COLOR.Improving} fontSize={11} fontWeight="bold">IMPROVING</text>

              {/* Tail lines — one Scatter per sector so each gets its own connecting line */}
              {sectors.map((s) => {
                const points: TailDatum[] = s.tail.map((t, idx) => ({
                  x: t.rsRatio,
                  y: t.rsMomentum,
                  ticker: s.ticker,
                  quadrant: s.quadrant,
                  isCurrent: idx === s.tail.length - 1,
                }));
                return (
                  <Scatter
                    key={`tail-${s.ticker}`}
                    data={points}
                    line={{ stroke: QUADRANT_COLOR[s.quadrant], strokeWidth: 1.2, strokeOpacity: 0.5 }}
                    lineType="joint"
                    shape={<TailDot />}
                    isAnimationActive={false}
                  />
                );
              })}

              {/* Current-position dots with labels */}
              <Scatter
                data={currentPoints}
                shape={<SectorLabel />}
                isAnimationActive={false}
              />
            </ScatterChart>
          </ResponsiveContainer>
        </div>

        {/* Legend */}
        <div className="grid grid-cols-4 gap-2 mt-3 text-xs">
          {(Object.keys(QUADRANT_COLOR) as Quadrant[]).map((q) => (
            <div key={q} className="flex items-center gap-2">
              <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: QUADRANT_COLOR[q] }} />
              <span className="text-terminal-text-secondary">{q}</span>
              <InfoTip text={QUADRANT_INFO[q]} />
            </div>
          ))}
        </div>

        {data.insufficientHistory?.length > 0 && (
          <div className="mt-3 text-xs text-terminal-warning">
            Insufficient history for: {data.insufficientHistory.join(", ")}. Run yahoo_daily_prices with a longer lookback.
          </div>
        )}
      </div>

      {/* Movers */}
      <div className="mb-3">
        <h2 className="text-base font-bold text-terminal-text-primary flex items-center gap-2">
          Quadrant Changes — Last 4 Weeks
          <InfoTip text="Sectors whose quadrant on the RRG has changed relative to 4 weekly bars ago. BUY = Improving → Leading. SELL = Weakening → Lagging. MOVED = any other quadrant change." />
        </h2>
        <p className="text-xs text-terminal-text-muted">
          For each mover, the top 3 ETFs (by average daily $-volume) and top 3 stocks (by market cap) in that sector from your watchlist.
        </p>
      </div>

      {movers.length === 0 ? (
        <div className="text-sm text-terminal-text-muted bg-terminal-bg-secondary border border-terminal-border rounded p-4">
          No sector changed quadrants in the last 4 weeks. The market is in a stable rotation regime.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {movers.map((s) => {
            const sig = s.signal ? SIGNAL_STYLE[s.signal] : null;
            return (
              <div key={s.ticker} className="bg-terminal-bg-secondary border border-terminal-border rounded p-3">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="text-sm font-bold text-terminal-text-primary">{s.sector}</div>
                    <div className="text-xs text-terminal-text-muted flex items-center gap-1">
                      <TickerLink ticker={s.ticker} className="font-mono text-terminal-accent hover:underline" />
                      <span>{s.name}</span>
                    </div>
                    <div className="text-xs mt-1">
                      <span style={{ color: s.quadrant4wAgo ? QUADRANT_COLOR[s.quadrant4wAgo] : "#666" }}>
                        {s.quadrant4wAgo ?? "?"}
                      </span>
                      <span className="text-terminal-text-muted"> → </span>
                      <span style={{ color: QUADRANT_COLOR[s.quadrant] }}>{s.quadrant}</span>
                    </div>
                  </div>
                  {sig && (
                    <span className={`px-2 py-0.5 text-xs font-bold rounded border ${sig.cls}`}>{sig.label}</span>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs text-terminal-text-muted mb-1 flex items-center gap-1">
                      Top ETFs
                      <InfoTip text="Top 3 ETFs in this sector from your watchlist, ranked by average dollar volume over the last 30 sessions." />
                    </div>
                    {s.topEtfs && s.topEtfs.length > 0 ? (
                      <ul className="text-xs space-y-1">
                        {s.topEtfs.map((e) => (
                          <li key={e.ticker} className="flex justify-between gap-2">
                            <TickerLink ticker={e.ticker} className="font-mono text-terminal-accent hover:underline" />
                            <span className="text-terminal-text-muted truncate">{fmtDollarVol(e.avgDollarVolume)}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="text-xs text-terminal-text-muted italic">None tracked</div>
                    )}
                  </div>
                  <div>
                    <div className="text-xs text-terminal-text-muted mb-1 flex items-center gap-1">
                      Top Stocks
                      <InfoTip text="Top 3 stocks in this sector from your watchlist, ranked by market cap (from security_fundamentals). Requires the yahoo_fundamentals pipeline to have populated market cap." />
                    </div>
                    {s.topStocks && s.topStocks.length > 0 ? (
                      <ul className="text-xs space-y-1">
                        {s.topStocks.map((st) => (
                          <li key={st.ticker} className="flex justify-between gap-2">
                            <TickerLink ticker={st.ticker} className="font-mono text-terminal-accent hover:underline" />
                            <span className="text-terminal-text-muted truncate">{fmtMarketCap(st.marketCapCents)}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="text-xs text-terminal-text-muted italic">None tracked</div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
