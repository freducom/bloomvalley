export interface Money {
  amount: number;
  currency: string;
}

export interface Security {
  id: number;
  ticker: string;
  isin: string | null;
  name: string;
  assetClass: "stock" | "bond" | "etf" | "crypto";
  currency: string;
  exchange: string | null;
  sector: string | null;
}

export interface Account {
  id: number;
  name: string;
  type: "regular" | "osakesaastotili" | "crypto_wallet" | "pension";
  currency: string;
}

export type ChangeDirection = "up" | "down" | "flat";

export interface MetricChange {
  value: string;
  direction: ChangeDirection;
}

export interface MarketStatus {
  exchange: string;
  status: "open" | "closed" | "pre-market" | "after-hours";
}

export interface PipelineHealth {
  name: string;
  status: "healthy" | "degraded" | "failed";
  lastRun: Date;
}

export interface PriceData {
  securityId: number;
  date: string;
  openCents: number | null;
  highCents: number | null;
  lowCents: number | null;
  closeCents: number;
  adjustedCloseCents: number | null;
  volume: number | null;
  currency: string;
  source: string;
}

export interface SecurityWithPrice extends Security {
  latestPrice?: PriceData;
  industry: string | null;
  country: string | null;
  isActive: boolean;
}
