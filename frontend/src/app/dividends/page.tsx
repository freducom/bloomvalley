"use client";

import { useState, useEffect } from "react";
import { apiGet } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { Private } from "@/lib/privacy";
import { TickerLink } from "@/components/ui/TickerLink";

interface UpcomingDividend {
  securityId: number;
  ticker: string;
  name: string;
  exDate: string;
  paymentDate: string | null;
  amountPerShareCents: number;
  currency: string;
  frequency: string | null;
  sharesHeld: string;
  totalCents: number;
  totalEurCents: number;
  currentYield: number | null;
}

interface HoldingYield {
  securityId: number;
  ticker: string;
  name: string;
  sharesHeld: string;
  annualDividendEurCents: number;
  dividendYield: number | null;
  yieldOnCost: number | null;
  frequency: string | null;
}

interface MonthlyBreakdown {
  month: string;
  amountEurCents: number;
}

interface YieldMetrics {
  portfolioDividendYield: number | null;
  yieldOnCost: number | null;
  annualDividendIncomeCents: number;
  monthlyBreakdown: MonthlyBreakdown[];
  byHolding: HoldingYield[];
}

interface CalendarEvent {
  securityId: number;
  ticker: string;
  name: string;
  exDate: string;
  paymentDate: string | null;
  amountPerShareCents: number;
  currency: string;
  frequency: string | null;
  sharesHeld: string | null;
  totalCents: number | null;
}

type Tab = "upcoming" | "yield" | "calendar" | "history";

const FREQ_LABELS: Record<string, string> = {
  monthly: "Monthly",
  quarterly: "Quarterly",
  semi_annual: "Semi-annual",
  annual: "Annual",
  irregular: "Irregular",
};

export default function DividendsPage() {
  const [tab, setTab] = useState<Tab>("upcoming");
  const [upcoming, setUpcoming] = useState<UpcomingDividend[]>([]);
  const [yieldData, setYieldData] = useState<YieldMetrics | null>(null);
  const [calendar, setCalendar] = useState<CalendarEvent[]>([]);
  const [history, setHistory] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(90);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      apiGet<UpcomingDividend[]>(`/dividends/upcoming?days=${days}`),
      apiGet<YieldMetrics>("/dividends/yield-metrics"),
      apiGet<CalendarEvent[]>("/dividends/calendar"),
      apiGet<CalendarEvent[]>("/dividends/history"),
    ])
      .then(([u, y, c, h]) => {
        setUpcoming(u);
        setYieldData(y);
        setCalendar(c);
        setHistory(h);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [days]);

  if (loading) {
    return (
      <div>
        <h1 className="text-3xl font-bold mb-6">Dividends</h1>
        <div className="flex items-center justify-center h-64 text-terminal-text-secondary">
          Loading dividend data...
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Dividends</h1>

      {/* Summary cards */}
      {yieldData && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-3">
            <div className="text-xs text-terminal-text-secondary">Annual Income (est.)</div>
            <div className="text-xl font-mono font-bold text-green-400">
              <Private>{formatCurrency(yieldData.annualDividendIncomeCents)}</Private>
            </div>
          </div>
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-3">
            <div className="text-xs text-terminal-text-secondary">Portfolio Yield</div>
            <div className="text-xl font-mono font-bold">
              {yieldData.portfolioDividendYield != null
                ? formatPercent(yieldData.portfolioDividendYield)
                : "—"}
            </div>
          </div>
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-3">
            <div className="text-xs text-terminal-text-secondary">Yield on Cost</div>
            <div className="text-xl font-mono font-bold">
              {yieldData.yieldOnCost != null ? formatPercent(yieldData.yieldOnCost) : "—"}
            </div>
          </div>
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-3">
            <div className="text-xs text-terminal-text-secondary">Upcoming ({days}d)</div>
            <div className="text-xl font-mono font-bold">
              {upcoming.length} event{upcoming.length !== 1 ? "s" : ""}
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-terminal-bg-secondary rounded-lg p-1 border border-terminal-border mb-6 w-fit">
        {(["upcoming", "yield", "calendar", "history"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 text-sm rounded capitalize ${
              tab === t
                ? "bg-terminal-bg-tertiary text-terminal-text-primary"
                : "text-terminal-text-secondary hover:text-terminal-text-primary"
            }`}
          >
            {t === "yield" ? "Yield Metrics" : t}
          </button>
        ))}
      </div>

      {tab === "upcoming" && <UpcomingTab data={upcoming} days={days} onDaysChange={setDays} />}
      {tab === "yield" && yieldData && <YieldTab data={yieldData} />}
      {tab === "calendar" && <CalendarTab data={calendar} />}
      {tab === "history" && <HistoryTab data={history} />}
    </div>
  );
}

function UpcomingTab({
  data,
  days,
  onDaysChange,
}: {
  data: UpcomingDividend[];
  days: number;
  onDaysChange: (d: number) => void;
}) {
  const totalEur = data.reduce((s, d) => s + d.totalEurCents, 0);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-terminal-text-secondary">
          Expected income: <span className="text-green-400 font-mono font-medium"><Private>{formatCurrency(totalEur)}</Private></span>
        </div>
        <div className="flex gap-1 bg-terminal-bg-secondary rounded p-0.5 border border-terminal-border">
          {[30, 60, 90].map((d) => (
            <button
              key={d}
              onClick={() => onDaysChange(d)}
              className={`px-2 py-0.5 text-xs rounded ${
                days === d ? "bg-terminal-bg-tertiary" : "text-terminal-text-secondary"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {data.length === 0 ? (
        <div className="text-center py-12 text-terminal-text-secondary">
          No upcoming dividends in the next {days} days.
        </div>
      ) : (
        <div className="border border-terminal-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-terminal-bg-tertiary text-terminal-text-secondary text-left">
                <th className="px-3 py-2 font-medium">Ex-Date</th>
                <th className="px-3 py-2 font-medium">Ticker</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Freq</th>
                <th className="px-3 py-2 font-medium text-right">Per Share</th>
                <th className="px-3 py-2 font-medium text-right">Shares</th>
                <th className="px-3 py-2 font-medium text-right">Total</th>
                <th className="px-3 py-2 font-medium text-right">Yield</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border">
              {data.map((d, i) => (
                <tr key={i} className="hover:bg-terminal-bg-secondary/50">
                  <td className="px-3 py-2 font-mono text-xs">{d.exDate}</td>
                  <td className="px-3 py-2 font-mono font-medium">
                    <TickerLink ticker={d.ticker} />
                  </td>
                  <td className="px-3 py-2 text-terminal-text-secondary truncate max-w-[200px]">{d.name}</td>
                  <td className="px-3 py-2 text-xs text-terminal-text-secondary">
                    {d.frequency ? FREQ_LABELS[d.frequency] || d.frequency : "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {formatCurrency(d.amountPerShareCents, d.currency)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono"><Private>{parseFloat(d.sharesHeld).toLocaleString()}</Private></td>
                  <td className="px-3 py-2 text-right font-mono text-green-400">
                    <Private>{formatCurrency(d.totalEurCents)}</Private>
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {d.currentYield != null ? formatPercent(d.currentYield) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function YieldTab({ data }: { data: YieldMetrics }) {
  // Build full 12-month grid (fill missing months with 0)
  const monthMap = new Map(data.monthlyBreakdown.map((m) => [m.month, m.amountEurCents]));
  const months: { month: string; label: string; amount: number }[] = [];
  const now = new Date();
  for (let i = 11; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = d.toLocaleDateString("en-US", { month: "short" });
    months.push({ month: key, label, amount: monthMap.get(key) || 0 });
  }
  const maxBar = Math.max(...months.map((m) => m.amount), 1);

  return (
    <div className="space-y-6">
      {/* Monthly income chart */}
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4">
        <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">
          Monthly Dividend Income (trailing 12m)
        </h3>
        <div className="flex items-end gap-2 h-48">
          {months.map((m) => {
            const pct = (m.amount / maxBar) * 100;
            return (
              <div key={m.month} className="flex-1 flex flex-col items-center justify-end h-full">
                {m.amount > 0 && (
                  <div className="text-[10px] font-mono text-terminal-text-secondary mb-1">
                    <Private>{(m.amount / 100).toFixed(0)}</Private>
                  </div>
                )}
                <div
                  className={`w-full rounded-t ${m.amount > 0 ? "bg-green-500/70" : "bg-terminal-bg-tertiary"}`}
                  style={{ height: `${Math.max(pct, m.amount > 0 ? 3 : 1)}%` }}
                />
                <div className="text-[10px] text-terminal-text-secondary mt-2">{m.label}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Holdings yield table */}
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4">
        <h3 className="text-sm font-medium text-terminal-text-secondary mb-3">Dividend Yield by Holding</h3>
        {data.byHolding.filter((h) => h.annualDividendEurCents > 0).length === 0 ? (
          <div className="text-center py-8 text-terminal-text-secondary">
            No dividend-paying holdings found.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-terminal-text-secondary text-left">
                <th className="px-3 py-2 font-medium">Ticker</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Freq</th>
                <th className="px-3 py-2 font-medium text-right">Shares</th>
                <th className="px-3 py-2 font-medium text-right">Annual (est.)</th>
                <th className="px-3 py-2 font-medium text-right">Yield</th>
                <th className="px-3 py-2 font-medium text-right">YoC</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border">
              {data.byHolding
                .filter((h) => h.annualDividendEurCents > 0)
                .map((h) => (
                  <tr key={h.securityId} className="hover:bg-terminal-bg-tertiary/50">
                    <td className="px-3 py-2 font-mono font-medium">
                      <TickerLink ticker={h.ticker} />
                    </td>
                    <td className="px-3 py-2 text-terminal-text-secondary truncate max-w-[200px]">{h.name}</td>
                    <td className="px-3 py-2 text-xs text-terminal-text-secondary">
                      {h.frequency ? FREQ_LABELS[h.frequency] || h.frequency : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      <Private>{parseFloat(h.sharesHeld).toLocaleString()}</Private>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-green-400">
                      <Private>{formatCurrency(h.annualDividendEurCents)}</Private>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {h.dividendYield != null ? formatPercent(h.dividendYield) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {h.yieldOnCost != null ? formatPercent(h.yieldOnCost) : "—"}
                    </td>
                  </tr>
                ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-terminal-border font-medium">
                <td className="px-3 py-2" colSpan={4}>
                  Total
                </td>
                <td className="px-3 py-2 text-right font-mono text-green-400">
                  <Private>{formatCurrency(data.annualDividendIncomeCents)}</Private>
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {data.portfolioDividendYield != null ? formatPercent(data.portfolioDividendYield) : "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {data.yieldOnCost != null ? formatPercent(data.yieldOnCost) : "—"}
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>
    </div>
  );
}

function CalendarTab({ data }: { data: CalendarEvent[] }) {
  // Group by month
  const byMonth: Record<string, CalendarEvent[]> = {};
  for (const ev of data) {
    const month = ev.exDate.slice(0, 7);
    if (!byMonth[month]) byMonth[month] = [];
    byMonth[month].push(ev);
  }

  const months = Object.keys(byMonth).sort();

  return (
    <div className="space-y-4">
      {months.length === 0 ? (
        <div className="text-center py-12 text-terminal-text-secondary">
          No dividend events in the selected period.
        </div>
      ) : (
        months.map((month) => {
          const monthLabel = new Date(month + "-01").toLocaleDateString("en-US", {
            year: "numeric",
            month: "long",
          });
          const events = byMonth[month];
          const total = events.reduce((s, e) => s + (e.totalCents || 0), 0);

          return (
            <div key={month} className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-medium">{monthLabel}</h3>
                {total > 0 && (
                  <span className="text-sm font-mono text-green-400"><Private>{formatCurrency(total)}</Private></span>
                )}
              </div>
              <div className="space-y-2">
                {events.map((ev, i) => (
                  <div key={i} className="flex items-center gap-3 text-sm">
                    <span className="font-mono text-xs text-terminal-text-secondary w-20">
                      {ev.exDate.slice(5)}
                    </span>
                    <span className="w-2 h-2 rounded-full bg-red-400" title="Ex-date" />
                    <TickerLink ticker={ev.ticker} className="font-mono text-terminal-accent hover:underline w-16" />
                    <span className="text-terminal-text-secondary flex-1 truncate">{ev.name}</span>
                    <span className="font-mono text-right w-24">
                      {formatCurrency(ev.amountPerShareCents, ev.currency)}/sh
                    </span>
                    {ev.totalCents != null && (
                      <span className="font-mono text-green-400 text-right w-24">
                        <Private>{formatCurrency(ev.totalCents, ev.currency)}</Private>
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

function HistoryTab({ data }: { data: CalendarEvent[] }) {
  // Group by year
  const years = [...new Set(data.map((d) => d.exDate.slice(0, 4)))].sort().reverse();
  const [yearFilter, setYearFilter] = useState("");
  const filtered = yearFilter ? data.filter((d) => d.exDate.startsWith(yearFilter)) : data;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <select
          value={yearFilter}
          onChange={(e) => setYearFilter(e.target.value)}
          className="bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-1.5 text-sm"
        >
          <option value="">All years</option>
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
        <span className="text-sm text-terminal-text-secondary">
          {filtered.length} event{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="border border-terminal-border rounded-lg overflow-hidden">
        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0">
              <tr className="bg-terminal-bg-tertiary text-terminal-text-secondary text-left">
                <th className="px-3 py-2 font-medium">Ex-Date</th>
                <th className="px-3 py-2 font-medium">Ticker</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Freq</th>
                <th className="px-3 py-2 font-medium text-right">Per Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border">
              {filtered.slice(0, 200).map((d, i) => (
                <tr key={i} className="hover:bg-terminal-bg-secondary/50">
                  <td className="px-3 py-2 font-mono text-xs">{d.exDate}</td>
                  <td className="px-3 py-2 font-mono font-medium">
                    <TickerLink ticker={d.ticker} />
                  </td>
                  <td className="px-3 py-2 text-terminal-text-secondary truncate max-w-[200px]">{d.name}</td>
                  <td className="px-3 py-2 text-xs text-terminal-text-secondary">
                    {d.frequency ? FREQ_LABELS[d.frequency] || d.frequency : "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {formatCurrency(d.amountPerShareCents, d.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
