const CURRENCY_SYMBOLS: Record<string, string> = {
  EUR: "\u20AC",
  USD: "$",
  GBP: "\u00A3",
  SEK: "kr",
};

/**
 * Format integer cents to currency string.
 * Example: formatCurrency(123456, "EUR") => "€1,234.56"
 */
export function formatCurrency(cents: number, currency: string = "EUR"): string {
  const symbol = CURRENCY_SYMBOLS[currency] || currency + " ";
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const frac = abs % 100;
  const sign = cents < 0 ? "-" : "";
  const formatted = whole.toLocaleString("en-US");
  return `${sign}${symbol}${formatted}.${frac.toString().padStart(2, "0")}`;
}

/**
 * Format a decimal percentage value.
 * Example: formatPercent(12.34, true) => "+12.34%"
 */
export function formatPercent(value: number, showSign: boolean = false): string {
  const sign = showSign && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/**
 * Format an ISO date string to "DD MMM YYYY".
 * Example: formatDate("2026-03-19") => "19 Mar 2026"
 */
export function formatDate(date: string): string {
  const d = new Date(date);
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const day = d.getDate();
  const month = months[d.getMonth()];
  const year = d.getFullYear();
  return `${day} ${month} ${year}`;
}

/**
 * Format large amounts with abbreviation.
 * Example: formatLargeNumber(123456789, "EUR") => "€1.23M"
 */
export function formatLargeNumber(cents: number, currency: string = "EUR"): string {
  const symbol = CURRENCY_SYMBOLS[currency] || currency + " ";
  const abs = Math.abs(cents / 100);
  const sign = cents < 0 ? "-" : "";

  if (abs >= 1_000_000_000) {
    return `${sign}${symbol}${(abs / 1_000_000_000).toFixed(2)}B`;
  }
  if (abs >= 1_000_000) {
    return `${sign}${symbol}${(abs / 1_000_000).toFixed(2)}M`;
  }
  return formatCurrency(cents, currency);
}
