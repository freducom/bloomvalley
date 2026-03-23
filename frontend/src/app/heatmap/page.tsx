"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { apiGetRaw } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";

/* ── Types ── */

interface HeatmapItem {
  securityId: number;
  ticker: string;
  name: string;
  sector: string | null;
  assetClass: string;
  currency: string;
  currentPriceCents: number;
  changePct: number;
  startPriceCents: number;
  endPriceCents: number;
  weight: number;
}

interface WatchlistOption {
  id: number;
  name: string;
  itemCount: number;
}

type Source = "holdings" | "watchlist" | string;
type Period = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y" | "YTD";

const PERIODS: { key: Period; label: string }[] = [
  { key: "1D", label: "1 Day" },
  { key: "1W", label: "1 Week" },
  { key: "1M", label: "1 Month" },
  { key: "3M", label: "3 Months" },
  { key: "6M", label: "6 Months" },
  { key: "1Y", label: "1 Year" },
  { key: "YTD", label: "YTD" },
];

function getColor(changePct: number): string {
  if (changePct >= 5) return "bg-green-600";
  if (changePct >= 3) return "bg-green-600/80";
  if (changePct >= 1) return "bg-green-700/70";
  if (changePct >= 0.01) return "bg-green-800/60";
  if (changePct > -0.01) return "bg-terminal-bg-tertiary";
  if (changePct > -1) return "bg-red-800/60";
  if (changePct > -3) return "bg-red-700/70";
  if (changePct > -5) return "bg-red-600/80";
  return "bg-red-600";
}

function getTextColor(changePct: number): string {
  if (Math.abs(changePct) >= 1) return "text-white";
  return "text-terminal-text-primary";
}

/* ── Simple treemap layout ── */

interface TreemapRect {
  item: HeatmapItem;
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Squarified treemap layout.
 * Takes items with weights and a container rect, returns positioned rects.
 */
function layoutTreemap(
  items: HeatmapItem[],
  containerW: number,
  containerH: number,
): TreemapRect[] {
  if (items.length === 0) return [];

  const totalWeight = items.reduce((s, i) => s + Math.max(i.weight, 1), 0);
  if (totalWeight === 0) return [];

  const totalArea = containerW * containerH;
  const sorted = [...items].sort((a, b) => b.weight - a.weight);

  const rects: TreemapRect[] = [];
  squarify(sorted, [], { x: 0, y: 0, w: containerW, h: containerH }, totalWeight, totalArea, rects);
  return rects;
}

function squarify(
  remaining: HeatmapItem[],
  row: HeatmapItem[],
  rect: { x: number; y: number; w: number; h: number },
  totalWeight: number,
  totalArea: number,
  rects: TreemapRect[],
) {
  if (remaining.length === 0) {
    if (row.length > 0) layoutRow(row, rect, totalWeight, totalArea, rects);
    return;
  }

  const next = remaining[0];
  const newRow = [...row, next];

  if (row.length === 0 || worstRatio(newRow, rect, totalWeight, totalArea) <= worstRatio(row, rect, totalWeight, totalArea)) {
    squarify(remaining.slice(1), newRow, rect, totalWeight, totalArea, rects);
  } else {
    const newRect = layoutRow(row, rect, totalWeight, totalArea, rects);
    squarify(remaining, [], newRect, totalWeight, totalArea, rects);
  }
}

function worstRatio(
  row: HeatmapItem[],
  rect: { x: number; y: number; w: number; h: number },
  totalWeight: number,
  totalArea: number,
): number {
  const rowWeight = row.reduce((s, i) => s + Math.max(i.weight, 1), 0);
  const rowArea = (rowWeight / totalWeight) * totalArea;
  const side = Math.min(rect.w, rect.h);
  if (side === 0) return Infinity;
  const rowLength = rowArea / side;

  let worst = 0;
  for (const item of row) {
    const itemArea = (Math.max(item.weight, 1) / totalWeight) * totalArea;
    const itemSide = itemArea / rowLength;
    const ratio = Math.max(rowLength / itemSide, itemSide / rowLength);
    worst = Math.max(worst, ratio);
  }
  return worst;
}

function layoutRow(
  row: HeatmapItem[],
  rect: { x: number; y: number; w: number; h: number },
  totalWeight: number,
  totalArea: number,
  rects: TreemapRect[],
): { x: number; y: number; w: number; h: number } {
  const rowWeight = row.reduce((s, i) => s + Math.max(i.weight, 1), 0);
  const rowArea = (rowWeight / totalWeight) * totalArea;
  const isHorizontal = rect.w >= rect.h;
  const side = isHorizontal ? rect.h : rect.w;
  const rowLength = side > 0 ? rowArea / side : 0;

  let offset = 0;
  for (const item of row) {
    const itemArea = (Math.max(item.weight, 1) / totalWeight) * totalArea;
    const itemLength = rowLength > 0 ? itemArea / rowLength : 0;

    if (isHorizontal) {
      rects.push({
        item,
        x: rect.x,
        y: rect.y + offset,
        w: rowLength,
        h: itemLength,
      });
    } else {
      rects.push({
        item,
        x: rect.x + offset,
        y: rect.y,
        w: itemLength,
        h: rowLength,
      });
    }
    offset += itemLength;
  }

  // Return remaining rect
  if (isHorizontal) {
    return { x: rect.x + rowLength, y: rect.y, w: rect.w - rowLength, h: rect.h };
  } else {
    return { x: rect.x, y: rect.y + rowLength, w: rect.w, h: rect.h - rowLength };
  }
}

/* ── Page ── */

export default function HeatmapPage() {
  const [source, setSource] = useState<Source>("holdings");
  const [period, setPeriod] = useState<Period>("1D");
  const [data, setData] = useState<HeatmapItem[]>([]);
  const [watchlists, setWatchlists] = useState<WatchlistOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [groupBy, setGroupBy] = useState<"none" | "sector" | "assetClass">("none");
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerW, setContainerW] = useState(1200);
  const [containerH, setContainerH] = useState(600);

  useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        const w = containerRef.current.clientWidth;
        setContainerW(w);
        // Aspect ratio: taller on mobile, wider on desktop
        setContainerH(w < 640 ? Math.round(w * 1.2) : Math.round(w * 0.5));
      }
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: WatchlistOption[] }>("/watchlists/");
        setWatchlists(res.data);
      } catch { /* */ }
    })();
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (source.startsWith("wl:")) {
        params.set("source", "watchlist");
        params.set("watchlistId", source.replace("wl:", ""));
      } else {
        params.set("source", source);
      }
      params.set("period", period);
      const res = await apiGetRaw<{ data: HeatmapItem[] }>(`/charts/heatmap?${params}`);
      setData(res.data);
    } catch { /* */ }
    setLoading(false);
  }, [source, period]);

  useEffect(() => { load(); }, [load]);

  // Group or render flat
  const grouped = useMemo(() => {
    if (groupBy === "none") return { All: data };
    const g: Record<string, HeatmapItem[]> = {};
    for (const item of data) {
      const key = groupBy === "sector" ? (item.sector || "Unknown") : item.assetClass;
      if (!g[key]) g[key] = [];
      g[key].push(item);
    }
    return g;
  }, [data, groupBy]);

  // Stats
  const gainers = data.filter((d) => d.changePct > 0).length;
  const losers = data.filter((d) => d.changePct < 0).length;
  const avgChange = data.length > 0 ? data.reduce((s, d) => s + d.changePct, 0) / data.length : 0;

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Heatmap</h1>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
        >
          <option value="holdings">My Holdings</option>
          <option value="watchlist">All Watchlists</option>
          {watchlists.map((w) => (
            <option key={w.id} value={`wl:${w.id}`}>
              {w.name} ({w.itemCount})
            </option>
          ))}
          <option value="all">All Securities</option>
        </select>

        <div className="flex gap-0 border border-terminal-border rounded overflow-hidden">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                period === p.key
                  ? "bg-terminal-accent text-terminal-bg-primary"
                  : "bg-terminal-bg-secondary text-terminal-text-secondary hover:text-terminal-text-primary"
              }`}
            >
              {p.key}
            </button>
          ))}
        </div>

        <select
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as typeof groupBy)}
          className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
        >
          <option value="none">No grouping</option>
          <option value="sector">By Sector</option>
          <option value="assetClass">By Asset Class</option>
        </select>

        <div className="flex items-center gap-4 text-xs text-terminal-text-secondary">
          <span className="text-terminal-positive">{gainers} up</span>
          <span className="text-terminal-negative">{losers} down</span>
          <span className={avgChange >= 0 ? "text-terminal-positive" : "text-terminal-negative"}>
            Avg: {formatPercent(avgChange, true)}
          </span>
          <span className="text-terminal-text-secondary">
            Size = {source === "holdings" ? "portfolio value" : "market cap"}
          </span>
        </div>
      </div>

      {/* Heatmap */}
      <div ref={containerRef}>
      {loading ? (
        <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>
      ) : data.length === 0 ? (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
          <p className="text-terminal-text-secondary text-sm">
            No price data available for the selected source and period.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(grouped)
            .sort(([, a], [, b]) => {
              const wA = a.reduce((s, i) => s + i.weight, 0);
              const wB = b.reduce((s, i) => s + i.weight, 0);
              return wB - wA;
            })
            .map(([group, items]) => {
              // Calculate group height proportional to its total weight (when grouped)
              const groupTotalWeight = items.reduce((s, i) => s + Math.max(i.weight, 1), 0);
              const allTotalWeight = data.reduce((s, i) => s + Math.max(i.weight, 1), 0);
              const groupH = groupBy === "none"
                ? containerH
                : Math.max(80, Math.round((groupTotalWeight / allTotalWeight) * containerH));

              const rects = layoutTreemap(items, containerW, groupH);

              return (
                <div key={group}>
                  {groupBy !== "none" && (
                    <h3 className="text-xs text-terminal-text-secondary mb-1 uppercase tracking-wider">
                      {group} ({items.length})
                    </h3>
                  )}
                  <div
                    className="relative border border-terminal-border rounded overflow-hidden w-full"
                    style={{ height: groupH }}
                  >
                    {rects.map((r) => {
                      const minDim = Math.min(r.w, r.h);
                      const showTicker = minDim >= 30;
                      const showPct = minDim >= 40;
                      const showPrice = r.w >= 70 && r.h >= 55;

                      return (
                        <div
                          key={r.item.securityId}
                          className={`absolute ${getColor(r.item.changePct)} flex flex-col items-center justify-center overflow-hidden cursor-default transition-opacity hover:opacity-80 border border-black/20`}
                          style={{
                            left: r.x,
                            top: r.y,
                            width: Math.max(r.w - 1, 1),
                            height: Math.max(r.h - 1, 1),
                          }}
                          title={`${r.item.ticker} — ${r.item.name}\n${formatPercent(r.item.changePct, true)}\n${formatCurrency(r.item.currentPriceCents, r.item.currency)}`}
                        >
                          {showTicker && (
                            <span className={`font-mono font-bold leading-tight ${getTextColor(r.item.changePct)} ${minDim >= 60 ? "text-xs" : "text-[10px]"}`}>
                              {r.item.ticker}
                            </span>
                          )}
                          {showPct && (
                            <span className={`font-mono font-bold leading-tight ${getTextColor(r.item.changePct)} ${minDim >= 60 ? "text-sm" : "text-xs"}`}>
                              {formatPercent(r.item.changePct, true)}
                            </span>
                          )}
                          {showPrice && (
                            <span className={`font-mono leading-tight opacity-70 ${getTextColor(r.item.changePct)} text-[10px]`}>
                              {formatCurrency(r.item.currentPriceCents, r.item.currency)}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
        </div>
      )}
      </div>

      {/* Legend */}
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-terminal-text-secondary">
        <span>Color:</span>
        <div className="flex gap-0.5">
          <div className="w-6 h-3 rounded-sm bg-red-600" />
          <div className="w-6 h-3 rounded-sm bg-red-700/70" />
          <div className="w-6 h-3 rounded-sm bg-red-800/60" />
          <div className="w-6 h-3 rounded-sm bg-terminal-bg-tertiary" />
          <div className="w-6 h-3 rounded-sm bg-green-800/60" />
          <div className="w-6 h-3 rounded-sm bg-green-700/70" />
          <div className="w-6 h-3 rounded-sm bg-green-600" />
        </div>
        <span>-5% ... 0% ... +5%</span>
        <span className="ml-4">Tile size = {source === "holdings" ? "portfolio value" : "market cap (price × avg volume)"}</span>
      </div>
    </div>
  );
}
