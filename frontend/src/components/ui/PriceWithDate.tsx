"use client";

/**
 * Wraps a price display with a hover tooltip showing when the price was fetched.
 * Usage: <PriceWithDate date="2026-04-08" source="yahoo_finance">€19.77</PriceWithDate>
 */
export function PriceWithDate({
  date,
  source,
  children,
}: {
  date?: string | null;
  source?: string | null;
  children: React.ReactNode;
}) {
  if (!date) return <>{children}</>;

  const d = new Date(date);
  const isFullTimestamp = date.includes("T");
  const formatted = isFullTimestamp
    ? d.toLocaleString("fi-FI")
    : d.toLocaleDateString("fi-FI");
  const title = source
    ? `Price as of ${formatted} (${source})`
    : `Price as of ${formatted}`;

  return (
    <span title={title} className="cursor-help border-b border-dotted border-terminal-text-tertiary/30">
      {children}
    </span>
  );
}
