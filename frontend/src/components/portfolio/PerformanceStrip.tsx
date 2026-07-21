"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Private } from "@/lib/privacy";
import { formatCurrency } from "@/lib/format";
import { InfoTip } from "@/components/ui/InfoTip";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

interface Totals {
  realizedGainCents: number;
  realizedLossCents: number;
  dividendCents: number;
  unrealizedGainCents: number;
  unrealizedLossCents: number;
  netCents: number;
}

function ytdRange(): { from: string; to: string } {
  const now = new Date();
  const from = `${now.getFullYear()}-01-01`;
  const to = now.toISOString().slice(0, 10);
  return { from, to };
}

function Amount({ cents }: { cents: number }) {
  const pos = cents > 0;
  const neg = cents < 0;
  const cls = pos ? "text-terminal-positive" : neg ? "text-terminal-negative" : "text-terminal-text-secondary";
  const sign = pos ? "+" : "";
  return <span className={cls}><Private>{sign}{formatCurrency(cents, "EUR")}</Private></span>;
}

function Cell({ label, cents, info }: { label: string; cents: number; info: string }) {
  return (
    <div className="flex flex-col">
      <div className="text-[10px] uppercase tracking-wider text-terminal-text-muted flex items-center gap-1">
        {label}
        <InfoTip text={info} />
      </div>
      <div className="text-base font-semibold mt-0.5"><Amount cents={cents} /></div>
    </div>
  );
}

const INFO = {
  realizedGain: "Sum of positive realized P&L from tax lots closed year-to-date.",
  realizedLoss: "Sum of negative realized P&L from tax lots closed year-to-date.",
  dividend: "Net dividends (after withholding tax) paid year-to-date.",
  unrealizedGain: "Period-attributed price gains on positions still held. V_end − V_start − net-cash-flow, positive rows only.",
  unrealizedLoss: "Same math as unrealized gains, negative rows only.",
  net: "Total year-to-date P&L across all buckets. Cash deposits and withdrawals excluded.",
};

export function PerformanceStrip() {
  const [totals, setTotals] = useState<Totals | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const { from, to } = ytdRange();
    (async () => {
      try {
        const url = `${API_BASE}/api/v1/performance?fromDate=${from}&toDate=${to}`;
        const res = await fetch(url, { cache: "no-store" });
        const json = await res.json().catch(() => null);
        if (!res.ok) throw new Error(json?.detail?.message || `API ${res.status}`);
        setTotals(json?.data?.totals || null);
      } catch (e: unknown) {
        setError(String((e as Error)?.message ?? e));
      }
    })();
  }, []);

  if (error) {
    return (
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-3 text-xs text-terminal-text-muted">
        YTD performance unavailable: {error}
      </div>
    );
  }

  if (!totals) {
    return (
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded p-3">
        <div className="text-xs text-terminal-text-muted animate-pulse">Loading YTD performance…</div>
      </div>
    );
  }

  return (
    <Link
      href="/performance"
      className="block bg-terminal-bg-secondary border border-terminal-border rounded p-3 hover:border-terminal-accent/50 transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold text-terminal-text-primary flex items-center gap-1">
          YTD Performance
          <InfoTip text="Portfolio P&L year-to-date, split into realized (closed positions), dividends (paid), and unrealized (price change on positions still held). Click to open the full breakdown with period picker." />
        </div>
        <span className="text-xs text-terminal-accent hover:underline">Full breakdown →</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <Cell label="Realized +" cents={totals.realizedGainCents}   info={INFO.realizedGain} />
        <Cell label="Realized −" cents={totals.realizedLossCents}   info={INFO.realizedLoss} />
        <Cell label="Dividends"  cents={totals.dividendCents}       info={INFO.dividend} />
        <Cell label="Unreal. +"  cents={totals.unrealizedGainCents} info={INFO.unrealizedGain} />
        <Cell label="Unreal. −"  cents={totals.unrealizedLossCents} info={INFO.unrealizedLoss} />
        <Cell label="Net"        cents={totals.netCents}            info={INFO.net} />
      </div>
    </Link>
  );
}
