import Link from "next/link";

export function TickerLink({ ticker, className }: { ticker: string; className?: string }) {
  return (
    <Link
      href={`/security/${encodeURIComponent(ticker)}`}
      className={className || "font-mono text-terminal-accent hover:underline"}
      onClick={(e) => e.stopPropagation()}
    >
      {ticker}
    </Link>
  );
}
