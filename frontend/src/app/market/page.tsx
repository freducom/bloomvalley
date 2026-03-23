"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import type { PriceData, SecurityWithPrice } from "@/lib/types";

interface PipelineInfo {
  name: string;
  source: string;
  isRunning: boolean;
  lastSuccess: string | null;
  lastRunStatus: string | null;
  lastRunRowsAffected: number | null;
}

export default function MarketPage() {
  const [securities, setSecurities] = useState<SecurityWithPrice[]>([]);
  const [prices, setPrices] = useState<PriceData[]>([]);
  const [pipelines, setPipelines] = useState<PipelineInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  const loadData = async () => {
    try {
      const [secs, latestPrices, pipelineData] = await Promise.all([
        apiGet<SecurityWithPrice[]>("/securities"),
        apiGet<PriceData[]>("/prices/latest"),
        apiGet<PipelineInfo[]>("/pipelines"),
      ]);

      setSecurities(secs);
      setPrices(latestPrices);
      setPipelines(pipelineData);
    } catch (e) {
      console.error("Failed to load market data:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 60000);
    return () => clearInterval(interval);
  }, []);

  const triggerPipeline = async (name: string) => {
    setTriggering(name);
    try {
      await apiPost(`/pipelines/${name}/run`);
      setTimeout(loadData, 5000);
      setTimeout(loadData, 15000);
      setTimeout(loadData, 30000);
    } catch (e) {
      console.error("Failed to trigger pipeline:", e);
    } finally {
      setTriggering(null);
    }
  };

  const priceMap = new Map(prices.map((p) => [p.securityId, p]));

  const filteredSecurities = securities.filter((s) => {
    if (filter === "all") return true;
    return s.assetClass === filter;
  });

  const assetClasses = ["all", "stock", "etf", "crypto"];

  if (loading) {
    return (
      <div className="animate-pulse">
        <div className="h-8 bg-terminal-bg-secondary rounded w-48 mb-6" />
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-12 bg-terminal-bg-secondary rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Market Data</h1>
        <div className="flex gap-2">
          {pipelines.map((p) => (
            <button
              key={p.name}
              onClick={() => triggerPipeline(p.name)}
              disabled={p.isRunning || triggering === p.name}
              className={`
                px-3 py-1.5 text-xs font-mono rounded border
                ${
                  p.isRunning
                    ? "border-terminal-warning text-terminal-warning opacity-50"
                    : "border-terminal-border text-terminal-text-secondary hover:text-terminal-text-primary hover:border-terminal-accent"
                }
                transition-colors
              `}
            >
              {p.isRunning ? "Running..." : `Fetch ${p.source}`}
            </button>
          ))}
        </div>
      </div>

      {/* Pipeline Status */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        {pipelines.map((p) => (
          <div
            key={p.name}
            className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-3"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-mono text-terminal-text-secondary">
                {p.name}
              </span>
              <span
                className={`text-xs px-2 py-0.5 rounded ${
                  p.lastRunStatus === "success"
                    ? "bg-terminal-positive/20 text-terminal-positive"
                    : p.lastRunStatus === "partial"
                    ? "bg-terminal-warning/20 text-terminal-warning"
                    : p.lastRunStatus === "failed"
                    ? "bg-terminal-negative/20 text-terminal-negative"
                    : "bg-terminal-bg-tertiary text-terminal-text-tertiary"
                }`}
              >
                {p.lastRunStatus || "never"}
              </span>
            </div>
            {p.lastSuccess && (
              <div className="text-xs text-terminal-text-tertiary mt-1">
                Last: {new Date(p.lastSuccess).toLocaleString()} ·{" "}
                {p.lastRunRowsAffected} rows
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 mb-4 border-b border-terminal-border pb-2">
        {assetClasses.map((ac) => (
          <button
            key={ac}
            onClick={() => setFilter(ac)}
            className={`
              px-3 py-1 text-sm font-mono rounded-t
              ${
                filter === ac
                  ? "bg-terminal-accent/20 text-terminal-accent border-b-2 border-terminal-accent"
                  : "text-terminal-text-secondary hover:text-terminal-text-primary"
              }
            `}
          >
            {ac === "all"
              ? `All (${securities.length})`
              : `${ac.toUpperCase()} (${
                  securities.filter((s) => s.assetClass === ac).length
                })`}
          </button>
        ))}
      </div>

      {/* Securities Table */}
      <div className="border border-terminal-border rounded-md overflow-hidden overflow-x-auto">
        <table className="w-full min-w-[700px]">
          <thead>
            <tr className="bg-terminal-bg-secondary text-terminal-text-secondary text-sm">
              <th className="text-left px-4 py-2 font-medium">Ticker</th>
              <th className="text-left px-4 py-2 font-medium">Name</th>
              <th className="text-left px-4 py-2 font-medium">Class</th>
              <th className="text-left px-4 py-2 font-medium">Sector</th>
              <th className="text-right px-4 py-2 font-medium">Price</th>
              <th className="text-right px-4 py-2 font-medium">Date</th>
              <th className="text-right px-4 py-2 font-medium">Source</th>
            </tr>
          </thead>
          <tbody>
            {filteredSecurities.map((sec) => {
              const price = priceMap.get(sec.id);
              return (
                <tr
                  key={sec.id}
                  className="border-t border-terminal-border hover:bg-terminal-bg-secondary/50 transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-terminal-accent text-sm">
                    {sec.ticker}
                  </td>
                  <td className="px-4 py-2 text-sm text-terminal-text-primary">
                    {sec.name}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`text-xs px-2 py-0.5 rounded font-mono ${
                        sec.assetClass === "stock"
                          ? "bg-terminal-info/20 text-terminal-info"
                          : sec.assetClass === "etf"
                          ? "bg-terminal-accent/20 text-terminal-accent"
                          : sec.assetClass === "crypto"
                          ? "bg-terminal-warning/20 text-terminal-warning"
                          : "bg-terminal-bg-tertiary text-terminal-text-tertiary"
                      }`}
                    >
                      {sec.assetClass}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-sm text-terminal-text-secondary">
                    {sec.sector || "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-sm">
                    {price ? (
                      <span className="text-terminal-text-primary">
                        {formatCurrency(price.closeCents, price.currency)}
                      </span>
                    ) : (
                      <span className="text-terminal-text-tertiary">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-terminal-text-tertiary font-mono">
                    {price?.date || "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-terminal-text-tertiary font-mono">
                    {price?.source || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 text-xs text-terminal-text-tertiary">
        {prices.length} prices loaded for {securities.length} securities
      </div>
    </div>
  );
}
