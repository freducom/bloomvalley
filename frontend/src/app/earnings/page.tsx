"use client";

import React, { useEffect, useState } from "react";
import { apiGet, apiGetRaw } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { TickerLink } from "@/components/ui/TickerLink";

interface CalendarEntry {
  securityId: number;
  ticker: string;
  name: string;
  reportDate: string;
  fiscalQuarter: string;
  epsEstimateCents: number | null;
  revenueEstimateCents: number | null;
}

interface Surprise {
  securityId: number;
  ticker: string;
  name: string;
  fiscalQuarter: string;
  reportDate: string | null;
  epsActualCents: number;
  epsEstimateCents: number | null;
  surprisePct: number;
  beat: boolean;
}

interface Estimate {
  id: number;
  fiscalQuarter: string;
  reportDate: string | null;
  epsActualCents: number | null;
  epsEstimateCents: number | null;
  surprisePct: number | null;
  revenueCents: number | null;
  revenueEstimateCents: number | null;
  epsYoyPct: number | null;
  source: string | null;
}

export default function EarningsPage() {
  const [calendar, setCalendar] = useState<CalendarEntry[]>([]);
  const [surprises, setSurprises] = useState<Surprise[]>([]);
  const [expandedTicker, setExpandedTicker] = useState<number | null>(null);
  const [estimates, setEstimates] = useState<Estimate[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiGetRaw<{ data: CalendarEntry[] }>("/earnings/calendar?days=90").catch(() => ({ data: [] })),
      apiGetRaw<{ data: Surprise[] }>("/earnings/surprises?limit=30").catch(() => ({ data: [] })),
    ]).then(([cal, sur]) => {
      setCalendar(cal.data);
      setSurprises(sur.data);
      setLoading(false);
    });
  }, []);

  const loadEstimates = async (securityId: number) => {
    if (expandedTicker === securityId) {
      setExpandedTicker(null);
      return;
    }
    setExpandedTicker(securityId);
    try {
      const res = await apiGetRaw<{ data: Estimate[] }>(`/earnings/estimates/${securityId}?limit=12`);
      setEstimates(res.data);
    } catch {
      setEstimates([]);
    }
  };

  const fmtEps = (cents: number | null) => {
    if (cents == null) return "--";
    return `$${(cents / 100).toFixed(2)}`;
  };

  if (loading) {
    return (
      <div className="animate-pulse">
        <div className="h-8 bg-terminal-bg-secondary rounded w-48 mb-6" />
        <div className="h-64 bg-terminal-bg-secondary rounded" />
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Earnings</h1>

      {/* Upcoming Earnings Calendar */}
      <div className="mb-8">
        <h2 className="text-sm font-mono font-semibold tracking-wider text-terminal-text-secondary mb-3">
          UPCOMING EARNINGS (90 DAYS)
        </h2>
        {calendar.length === 0 ? (
          <div className="text-sm text-terminal-text-tertiary bg-terminal-bg-secondary border border-terminal-border rounded p-4">
            No upcoming earnings dates found for your holdings. Run the finnhub_earnings pipeline to fetch data.
          </div>
        ) : (
          <div className="border border-terminal-border rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-terminal-bg-secondary text-terminal-text-secondary">
                  <th className="text-left px-4 py-2 font-medium">Date</th>
                  <th className="text-left px-4 py-2 font-medium">Ticker</th>
                  <th className="text-left px-4 py-2 font-medium">Name</th>
                  <th className="text-left px-4 py-2 font-medium">Quarter</th>
                  <th className="text-right px-4 py-2 font-medium">EPS Est.</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-terminal-border">
                {calendar.map((c, i) => (
                  <tr key={i} className="hover:bg-terminal-bg-secondary/50">
                    <td className="px-4 py-2 font-mono">{c.reportDate}</td>
                    <td className="px-4 py-2 font-mono font-medium"><TickerLink ticker={c.ticker} /></td>
                    <td className="px-4 py-2 text-terminal-text-secondary">{c.name}</td>
                    <td className="px-4 py-2">{c.fiscalQuarter}</td>
                    <td className="px-4 py-2 text-right font-mono">{fmtEps(c.epsEstimateCents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent Earnings Surprises */}
      <div>
        <h2 className="text-sm font-mono font-semibold tracking-wider text-terminal-text-secondary mb-3">
          RECENT EARNINGS SURPRISES
        </h2>
        {surprises.length === 0 ? (
          <div className="text-sm text-terminal-text-tertiary bg-terminal-bg-secondary border border-terminal-border rounded p-4">
            No earnings surprise data yet. Run the finnhub_earnings pipeline to fetch data.
          </div>
        ) : (
          <div className="border border-terminal-border rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-terminal-bg-secondary text-terminal-text-secondary">
                  <th className="text-left px-4 py-2 font-medium">Ticker</th>
                  <th className="text-left px-4 py-2 font-medium">Quarter</th>
                  <th className="text-left px-4 py-2 font-medium">Date</th>
                  <th className="text-right px-4 py-2 font-medium">Actual</th>
                  <th className="text-right px-4 py-2 font-medium">Estimate</th>
                  <th className="text-right px-4 py-2 font-medium">Surprise</th>
                  <th className="text-center px-4 py-2 font-medium">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-terminal-border">
                {surprises.map((s, i) => (
                  <React.Fragment key={`${s.securityId}-${s.fiscalQuarter}`}>
                    <tr
                      className="hover:bg-terminal-bg-secondary/50 cursor-pointer"
                      onClick={() => loadEstimates(s.securityId)}
                    >
                      <td className="px-4 py-2 font-mono font-medium"><TickerLink ticker={s.ticker} /></td>
                      <td className="px-4 py-2">{s.fiscalQuarter}</td>
                      <td className="px-4 py-2 font-mono text-terminal-text-secondary">{s.reportDate || "--"}</td>
                      <td className="px-4 py-2 text-right font-mono">{fmtEps(s.epsActualCents)}</td>
                      <td className="px-4 py-2 text-right font-mono text-terminal-text-secondary">{fmtEps(s.epsEstimateCents)}</td>
                      <td className={`px-4 py-2 text-right font-mono font-medium ${s.surprisePct >= 0 ? "text-terminal-positive" : "text-terminal-negative"}`}>
                        {s.surprisePct >= 0 ? "+" : ""}{s.surprisePct.toFixed(1)}%
                      </td>
                      <td className="px-4 py-2 text-center">
                        <span className={`text-xs px-2 py-0.5 rounded font-mono font-medium ${
                          s.beat
                            ? "bg-terminal-positive/20 text-terminal-positive"
                            : "bg-terminal-negative/20 text-terminal-negative"
                        }`}>
                          {s.beat ? "BEAT" : "MISS"}
                        </span>
                      </td>
                    </tr>
                    {/* Expanded: earnings history */}
                    {expandedTicker === s.securityId && (
                      <tr key={`exp-${i}`}>
                        <td colSpan={7} className="bg-terminal-bg-tertiary px-4 py-3">
                          <div className="text-xs font-mono text-terminal-text-secondary mb-2">
                            EARNINGS HISTORY — {s.ticker} ({s.name})
                          </div>
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-terminal-text-tertiary">
                                <th className="text-left py-1">Quarter</th>
                                <th className="text-left py-1">Date</th>
                                <th className="text-right py-1">Actual EPS</th>
                                <th className="text-right py-1">Est. EPS</th>
                                <th className="text-right py-1">Surprise</th>
                                <th className="text-right py-1">EPS YoY</th>
                                <th className="text-right py-1">Revenue</th>
                                <th className="text-left py-1">Source</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-terminal-border/50">
                              {estimates.map((e) => (
                                <tr key={e.id}>
                                  <td className="py-1">{e.fiscalQuarter}</td>
                                  <td className="py-1 text-terminal-text-tertiary">{e.reportDate || "--"}</td>
                                  <td className="py-1 text-right font-mono">{fmtEps(e.epsActualCents)}</td>
                                  <td className="py-1 text-right font-mono text-terminal-text-tertiary">{fmtEps(e.epsEstimateCents)}</td>
                                  <td className={`py-1 text-right font-mono ${e.surprisePct != null && e.surprisePct >= 0 ? "text-terminal-positive" : e.surprisePct != null ? "text-terminal-negative" : ""}`}>
                                    {e.surprisePct != null ? `${e.surprisePct >= 0 ? "+" : ""}${e.surprisePct.toFixed(1)}%` : "--"}
                                  </td>
                                  <td className={`py-1 text-right font-mono ${e.epsYoyPct != null && e.epsYoyPct >= 0 ? "text-terminal-positive" : e.epsYoyPct != null ? "text-terminal-negative" : ""}`}>
                                    {e.epsYoyPct != null ? `${e.epsYoyPct >= 0 ? "+" : ""}${e.epsYoyPct.toFixed(1)}%` : "--"}
                                  </td>
                                  <td className="py-1 text-right font-mono">{e.revenueCents != null ? formatCurrency(e.revenueCents, "USD") : "--"}</td>
                                  <td className="py-1 text-terminal-text-tertiary">{e.source || "--"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
