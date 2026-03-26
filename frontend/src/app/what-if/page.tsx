"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { MetricCard } from "@/components/ui/MetricCard";
import { Private } from "@/lib/privacy";
import { formatCurrency, formatPercent, formatLargeNumber } from "@/lib/format";
import { apiGetRaw } from "@/lib/api";

/* ── Types ── */

interface SecurityResult {
  id: number;
  ticker: string;
  name: string;
  assetClass: string;
}

interface RiskMetrics {
  volatility: number;
  sharpe: number;
  var95: number;
}

interface AllocationMap {
  equity: number;
  fixed_income: number;
  crypto: number;
  cash: number;
}

interface WhatIfResult {
  trade: {
    ticker: string;
    name: string;
    action: string;
    quantity: string;
    priceCents: number;
    priceCurrency: string;
    totalEurCents: number;
  };
  current: {
    totalValueCents: number;
    allocation: AllocationMap;
    risk: RiskMetrics;
  };
  proposed: {
    totalValueCents: number;
    allocation: AllocationMap;
    risk: RiskMetrics;
  };
  glidepathTarget: AllocationMap;
  delta: {
    valueCents: number;
    volatility: number;
    sharpe: number;
    var95: number;
  };
}

/* ── Page ── */

export default function WhatIfPage() {
  // Security search
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SecurityResult[]>([]);
  const [selectedSecurity, setSelectedSecurity] = useState<SecurityResult | null>(null);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchTimeout = useRef<ReturnType<typeof setTimeout>>();

  // Trade params
  const [action, setAction] = useState<"buy" | "sell">("buy");
  const [inputMode, setInputMode] = useState<"quantity" | "amount">("amount");
  const [quantityStr, setQuantityStr] = useState("10");
  const [amountEur, setAmountEur] = useState(5000);

  // Result
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounced search
  useEffect(() => {
    if (query.length < 2) {
      setSearchResults([]);
      setShowDropdown(false);
      return;
    }

    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(async () => {
      try {
        const res = await apiGetRaw<{ data: SecurityResult[] }>(
          `/securities?search=${encodeURIComponent(query)}&limit=10`
        );
        setSearchResults(res.data || []);
        setShowDropdown(true);
      } catch {
        setSearchResults([]);
      }
    }, 300);

    return () => {
      if (searchTimeout.current) clearTimeout(searchTimeout.current);
    };
  }, [query]);

  const selectSecurity = (sec: SecurityResult) => {
    setSelectedSecurity(sec);
    setQuery(sec.ticker);
    setShowDropdown(false);
    setResult(null);
  };

  const runSimulation = useCallback(async () => {
    if (!selectedSecurity) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const params = new URLSearchParams({
        securityId: String(selectedSecurity.id),
        action,
      });
      if (inputMode === "quantity") {
        params.set("quantity", quantityStr);
      } else {
        params.set("amountEurCents", String(amountEur * 100));
      }

      const res = await apiGetRaw<{ data: WhatIfResult }>(`/portfolio/what-if?${params}`);
      setResult(res.data);
    } catch (e: any) {
      setError(e.message || "Simulation failed");
    } finally {
      setLoading(false);
    }
  }, [selectedSecurity, action, inputMode, quantityStr, amountEur]);

  const d = result?.delta;
  const c = result?.current;
  const p = result?.proposed;

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-terminal-text-primary">What-If Simulator</h1>
        <p className="text-sm text-terminal-text-secondary mt-1">
          Preview how a trade affects your portfolio risk, allocation, and glidepath
        </p>
      </div>

      {/* Input Panel */}
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          {/* Security Search */}
          <div className="lg:col-span-2 relative">
            <label className="block text-xs text-terminal-text-tertiary mb-1">Security</label>
            <input
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSelectedSecurity(null);
                setResult(null);
              }}
              placeholder="Search by ticker or name..."
              className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-3 py-2 text-sm font-mono text-terminal-text-primary focus:border-terminal-accent focus:outline-none"
            />
            {showDropdown && searchResults.length > 0 && (
              <div className="absolute z-50 top-full mt-1 w-full bg-terminal-bg-tertiary border border-terminal-border rounded-md shadow-lg max-h-60 overflow-y-auto">
                {searchResults.map((sec) => (
                  <button
                    key={sec.id}
                    onClick={() => selectSecurity(sec)}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-terminal-bg-hover transition-colors flex items-center gap-2"
                  >
                    <span className="font-mono font-medium text-terminal-accent">{sec.ticker}</span>
                    <span className="text-terminal-text-secondary truncate">{sec.name}</span>
                    <span className="text-xs text-terminal-text-tertiary ml-auto">{sec.assetClass}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Buy/Sell Toggle */}
          <div>
            <label className="block text-xs text-terminal-text-tertiary mb-1">Action</label>
            <div className="flex gap-1">
              {(["buy", "sell"] as const).map((a) => (
                <button
                  key={a}
                  onClick={() => setAction(a)}
                  className={`flex-1 px-3 py-2 text-sm font-medium rounded transition-colors ${
                    action === a
                      ? a === "buy"
                        ? "bg-terminal-positive/20 text-terminal-positive border border-terminal-positive/50"
                        : "bg-terminal-negative/20 text-terminal-negative border border-terminal-negative/50"
                      : "bg-terminal-bg-primary border border-terminal-border text-terminal-text-secondary"
                  }`}
                >
                  {a.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Amount Input */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-terminal-text-tertiary">
                {inputMode === "quantity" ? "Shares" : "EUR Amount"}
              </label>
              <button
                onClick={() => setInputMode(inputMode === "quantity" ? "amount" : "quantity")}
                className="text-[10px] text-terminal-accent hover:underline"
              >
                Switch to {inputMode === "quantity" ? "EUR" : "shares"}
              </button>
            </div>
            <input
              type="number"
              value={inputMode === "quantity" ? quantityStr : amountEur}
              onChange={(e) => {
                if (inputMode === "quantity") setQuantityStr(e.target.value);
                else setAmountEur(Number(e.target.value));
              }}
              className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-3 py-2 text-sm font-mono text-terminal-text-primary focus:border-terminal-accent focus:outline-none"
              min={0}
              step={inputMode === "quantity" ? 1 : 500}
            />
          </div>

          {/* Simulate Button */}
          <div className="flex items-end">
            <button
              onClick={runSimulation}
              disabled={!selectedSecurity || loading}
              className="w-full px-4 py-2 text-sm font-medium rounded bg-terminal-accent/20 text-terminal-accent border border-terminal-accent/50 hover:bg-terminal-accent/30 transition-colors disabled:opacity-50"
            >
              {loading ? "Simulating..." : "Simulate"}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="text-sm text-terminal-warning bg-terminal-warning/10 border border-terminal-warning/20 rounded p-3">
          {error}
        </div>
      )}

      {/* Results */}
      {result && c && p && d && (
        <>
          {/* Trade Summary */}
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
            <div className="flex items-center gap-3 text-sm">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                result.trade.action === "buy"
                  ? "bg-terminal-positive/20 text-terminal-positive"
                  : "bg-terminal-negative/20 text-terminal-negative"
              }`}>
                {result.trade.action.toUpperCase()}
              </span>
              <span className="font-mono font-medium text-terminal-accent">{result.trade.ticker}</span>
              <span className="text-terminal-text-secondary">{result.trade.name}</span>
              <span className="ml-auto font-mono">
                {result.trade.quantity} shares @ {formatCurrency(result.trade.priceCents, result.trade.priceCurrency)}
              </span>
              <span className="font-mono font-medium">
                = <Private>{formatCurrency(result.trade.totalEurCents)}</Private>
              </span>
            </div>
          </div>

          {/* Risk Metric Deltas */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Volatility"
              value={formatPercent(p.risk.volatility)}
              change={`${d.volatility >= 0 ? "+" : ""}${d.volatility.toFixed(2)}pp`}
              changeType={d.volatility <= 0 ? "positive" : "negative"}
            />
            <MetricCard
              label="Sharpe Ratio"
              value={p.risk.sharpe.toFixed(3)}
              change={`${d.sharpe >= 0 ? "+" : ""}${d.sharpe.toFixed(3)}`}
              changeType={d.sharpe >= 0 ? "positive" : "negative"}
            />
            <MetricCard
              label="VaR 95% (1D)"
              value={formatPercent(p.risk.var95)}
              change={`${d.var95 >= 0 ? "+" : ""}${d.var95.toFixed(2)}pp`}
              changeType={d.var95 <= 0 ? "positive" : "negative"}
            />
            <MetricCard
              label="Portfolio Value"
              value={<Private>{formatLargeNumber(p.totalValueCents)}</Private>}
              change={`${d.valueCents >= 0 ? "+" : ""}${formatCurrency(d.valueCents)}`}
              changeType="neutral"
            />
          </div>

          {/* Allocation Comparison */}
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
            <h3 className="text-sm font-medium text-terminal-text-secondary mb-4">
              Allocation Comparison
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-terminal-text-tertiary text-xs text-left">
                  <th className="pb-2 font-medium">Asset Class</th>
                  <th className="pb-2 font-medium text-right">Current</th>
                  <th className="pb-2 font-medium text-right">Proposed</th>
                  <th className="pb-2 font-medium text-right">Target</th>
                  <th className="pb-2 font-medium text-right">Drift</th>
                  <th className="pb-2 font-medium w-1/3">Comparison</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-terminal-border">
                {(["equity", "fixed_income", "crypto", "cash"] as const).map((cat) => {
                  const cur = c.allocation[cat];
                  const prop = p.allocation[cat];
                  const tgt = result.glidepathTarget[cat];
                  const drift = prop - tgt;
                  const label = { equity: "Equities", fixed_income: "Fixed Income", crypto: "Crypto", cash: "Cash" }[cat];
                  const color = { equity: "#3B82F6", fixed_income: "#22D3EE", crypto: "#F59E0B", cash: "#6B7280" }[cat];

                  return (
                    <tr key={cat}>
                      <td className="py-2 font-medium">{label}</td>
                      <td className="py-2 text-right font-mono">{formatPercent(cur)}</td>
                      <td className="py-2 text-right font-mono">{formatPercent(prop)}</td>
                      <td className="py-2 text-right font-mono text-terminal-text-tertiary">{formatPercent(tgt)}</td>
                      <td className="py-2 text-right font-mono">
                        <span className={Math.abs(drift) >= 5 ? "text-terminal-negative" : Math.abs(drift) >= 2 ? "text-terminal-warning" : "text-terminal-text-secondary"}>
                          {drift >= 0 ? "+" : ""}{drift.toFixed(1)}pp
                        </span>
                      </td>
                      <td className="py-2">
                        <div className="flex items-center gap-1 h-4">
                          <div className="flex-1 bg-terminal-bg-primary rounded-sm overflow-hidden h-2">
                            <div className="h-full rounded-sm opacity-50" style={{ width: `${cur}%`, backgroundColor: color }} />
                          </div>
                          <div className="flex-1 bg-terminal-bg-primary rounded-sm overflow-hidden h-2">
                            <div className="h-full rounded-sm" style={{ width: `${prop}%`, backgroundColor: color }} />
                          </div>
                        </div>
                        <div className="flex text-[9px] text-terminal-text-tertiary mt-0.5">
                          <span className="flex-1">Current</span>
                          <span className="flex-1">Proposed</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
