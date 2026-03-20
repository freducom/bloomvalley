"use client";

import { useEffect, useState, useRef, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { apiGet, apiGetRaw } from "@/lib/api";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  ColorType,
} from "lightweight-charts";

interface SecurityOption {
  id: number;
  ticker: string;
  name: string;
  assetClass: string;
  currency: string;
}

interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

interface ChartData {
  security: {
    id: number;
    ticker: string;
    name: string;
    currency: string;
  };
  candles: Candle[];
  indicators: Record<string, unknown>;
}

const PERIODS = ["1M", "3M", "6M", "1Y", "2Y", "5Y", "MAX"] as const;
const INDICATORS = [
  { key: "sma20", label: "SMA 20" },
  { key: "sma50", label: "SMA 50" },
  { key: "ema20", label: "EMA 20" },
  { key: "bollinger", label: "Bollinger" },
  { key: "rsi", label: "RSI" },
  { key: "macd", label: "MACD" },
] as const;

const CHART_COLORS = {
  bg: "#0A0E17",
  text: "#9CA3AF",
  border: "#1F2937",
  accent: "#8B5CF6",
  positive: "#22C55E",
  negative: "#EF4444",
  info: "#3B82F6",
  warning: "#F59E0B",
};

function ChartsContent() {
  const searchParams = useSearchParams();
  const initialSecurityId = searchParams.get("security");

  const [securities, setSecurities] = useState<SecurityOption[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(
    initialSecurityId ? parseInt(initialSecurityId) : null
  );
  const [period, setPeriod] = useState<string>("1Y");
  const [activeIndicators, setActiveIndicators] = useState<string[]>([]);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [chartType, setChartType] = useState<"candlestick" | "line">(
    "candlestick"
  );

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await apiGet<SecurityOption[]>("/securities?limit=200");
        setSecurities(data);
      } catch (e) {
        console.error("Failed to load securities:", e);
      }
    };
    load();
  }, []);

  const loadChartData = useCallback(async () => {
    if (!selectedId) return;
    setLoading(true);
    try {
      const indicators = activeIndicators.join(",");
      const result = await apiGetRaw<{ data: ChartData }>(
        `/charts/${selectedId}/ohlc?period=${period}&indicators=${indicators}`
      );
      setChartData(result.data);
    } catch (e) {
      console.error("Failed to load chart data:", e);
    } finally {
      setLoading(false);
    }
  }, [selectedId, period, activeIndicators]);

  useEffect(() => {
    loadChartData();
  }, [loadChartData]);

  // Render chart
  useEffect(() => {
    if (!chartData || !chartContainerRef.current) return;
    if (chartData.candles.length === 0) return;

    // Cleanup old charts
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }
    if (rsiChartRef.current) {
      rsiChartRef.current.remove();
      rsiChartRef.current = null;
    }
    if (macdChartRef.current) {
      macdChartRef.current.remove();
      macdChartRef.current = null;
    }

    const hasRsi = activeIndicators.includes("rsi");
    const hasMacd = activeIndicators.includes("macd");

    // Main chart
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: CHART_COLORS.bg },
        textColor: CHART_COLORS.text,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: CHART_COLORS.border },
        horzLines: { color: CHART_COLORS.border },
      },
      crosshair: {
        mode: 0,
      },
      rightPriceScale: {
        borderColor: CHART_COLORS.border,
      },
      timeScale: {
        borderColor: CHART_COLORS.border,
        timeVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
    });
    chartRef.current = chart;

    // Main price series
    if (chartType === "candlestick") {
      const candleSeries = chart.addCandlestickSeries({
        upColor: CHART_COLORS.positive,
        downColor: CHART_COLORS.negative,
        borderUpColor: CHART_COLORS.positive,
        borderDownColor: CHART_COLORS.negative,
        wickUpColor: CHART_COLORS.positive,
        wickDownColor: CHART_COLORS.negative,
      });
      candleSeries.setData(chartData.candles as Parameters<typeof candleSeries.setData>[0]);
    } else {
      const lineSeries = chart.addLineSeries({
        color: CHART_COLORS.accent,
        lineWidth: 2,
      });
      lineSeries.setData(
        chartData.candles.map((c) => ({ time: c.time, value: c.close })) as Parameters<typeof lineSeries.setData>[0]
      );
    }

    const indicators = chartData.indicators as Record<string, unknown>;

    // Overlay indicators (SMA, EMA, Bollinger)
    const overlayColors: Record<string, string> = {
      sma20: CHART_COLORS.info,
      sma50: CHART_COLORS.warning,
      ema20: "#EC4899",
    };

    for (const key of ["sma20", "sma50", "ema20"]) {
      if (indicators[key] && Array.isArray(indicators[key])) {
        const series = chart.addLineSeries({
          color: overlayColors[key],
          lineWidth: 1,
          lastValueVisible: false,
          priceLineVisible: false,
        });
        series.setData(indicators[key] as Parameters<typeof series.setData>[0]);
      }
    }

    // Bollinger Bands
    if (indicators.bollinger) {
      const bb = indicators.bollinger as Record<string, unknown[]>;
      if (bb.upper) {
        const upperSeries = chart.addLineSeries({
          color: "rgba(139, 92, 246, 0.5)",
          lineWidth: 1,
          lastValueVisible: false,
          priceLineVisible: false,
        });
        upperSeries.setData(bb.upper as Parameters<typeof upperSeries.setData>[0]);
      }
      if (bb.lower) {
        const lowerSeries = chart.addLineSeries({
          color: "rgba(139, 92, 246, 0.5)",
          lineWidth: 1,
          lastValueVisible: false,
          priceLineVisible: false,
        });
        lowerSeries.setData(bb.lower as Parameters<typeof lowerSeries.setData>[0]);
      }
    }

    // RSI pane
    if (hasRsi && rsiContainerRef.current && indicators.rsi) {
      const rsiChart = createChart(rsiContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: CHART_COLORS.bg },
          textColor: CHART_COLORS.text,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: CHART_COLORS.border },
          horzLines: { color: CHART_COLORS.border },
        },
        rightPriceScale: {
          borderColor: CHART_COLORS.border,
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
        timeScale: {
          borderColor: CHART_COLORS.border,
          visible: !hasMacd,
        },
        width: rsiContainerRef.current.clientWidth,
        height: 120,
      });
      rsiChartRef.current = rsiChart;

      const rsiSeries = rsiChart.addLineSeries({
        color: CHART_COLORS.accent,
        lineWidth: 1,
        priceLineVisible: false,
      });
      rsiSeries.setData(indicators.rsi as Parameters<typeof rsiSeries.setData>[0]);

      // Sync time scales
      chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
      });
      rsiChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) chart.timeScale().setVisibleLogicalRange(range);
      });
    }

    // MACD pane
    if (hasMacd && macdContainerRef.current && indicators.macd) {
      const macdData = indicators.macd as Record<string, unknown[]>;
      const macdChart = createChart(macdContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: CHART_COLORS.bg },
          textColor: CHART_COLORS.text,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: CHART_COLORS.border },
          horzLines: { color: CHART_COLORS.border },
        },
        rightPriceScale: {
          borderColor: CHART_COLORS.border,
        },
        timeScale: {
          borderColor: CHART_COLORS.border,
        },
        width: macdContainerRef.current.clientWidth,
        height: 120,
      });
      macdChartRef.current = macdChart;

      if (macdData.macd) {
        const macdLine = macdChart.addLineSeries({
          color: CHART_COLORS.info,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        macdLine.setData(macdData.macd as Parameters<typeof macdLine.setData>[0]);
      }
      if (macdData.signal) {
        const signalLine = macdChart.addLineSeries({
          color: CHART_COLORS.warning,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        signalLine.setData(macdData.signal as Parameters<typeof signalLine.setData>[0]);
      }
      if (macdData.histogram) {
        const histSeries = macdChart.addHistogramSeries({
          color: CHART_COLORS.positive,
        });
        const histData = (macdData.histogram as { time: string; value: number }[]).map(
          (d) => ({
            ...d,
            color: d.value >= 0 ? CHART_COLORS.positive : CHART_COLORS.negative,
          })
        );
        histSeries.setData(histData as Parameters<typeof histSeries.setData>[0]);
      }

      // Sync time scales
      chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) macdChart.timeScale().setVisibleLogicalRange(range);
      });
      macdChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) chart.timeScale().setVisibleLogicalRange(range);
      });
    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
      if (rsiContainerRef.current && rsiChartRef.current) {
        rsiChartRef.current.applyOptions({
          width: rsiContainerRef.current.clientWidth,
        });
      }
      if (macdContainerRef.current && macdChartRef.current) {
        macdChartRef.current.applyOptions({
          width: macdContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      rsiChartRef.current?.remove();
      macdChartRef.current?.remove();
      chartRef.current = null;
      rsiChartRef.current = null;
      macdChartRef.current = null;
    };
  }, [chartData, chartType, activeIndicators]);

  const toggleIndicator = (key: string) => {
    setActiveIndicators((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const filteredSecurities = securities.filter(
    (s) =>
      searchTerm === "" ||
      s.ticker.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const selectedSecurity = securities.find((s) => s.id === selectedId);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Charts</h1>
      </div>

      {/* Security selector */}
      <div className="flex items-center gap-4 mb-4">
        <div className="relative flex-1 max-w-sm">
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder={
              selectedSecurity
                ? `${selectedSecurity.ticker} — ${selectedSecurity.name}`
                : "Search security..."
            }
            className="w-full bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-1.5 font-mono text-sm text-terminal-text-primary placeholder-terminal-text-tertiary focus:outline-none focus:border-terminal-accent"
          />
          {searchTerm && (
            <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-terminal-bg-secondary border border-terminal-border rounded-md shadow-lg max-h-64 overflow-y-auto">
              {filteredSecurities.map((s) => (
                <button
                  key={s.id}
                  onClick={() => {
                    setSelectedId(s.id);
                    setSearchTerm("");
                  }}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-terminal-bg-tertiary transition-colors flex items-center gap-3"
                >
                  <span className="font-mono text-terminal-accent w-20 shrink-0">
                    {s.ticker}
                  </span>
                  <span className="truncate">{s.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Chart type toggle */}
        <div className="flex gap-1">
          {(["candlestick", "line"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setChartType(t)}
              className={`px-3 py-1 text-sm font-mono rounded ${
                chartType === t
                  ? "bg-terminal-accent/20 text-terminal-accent"
                  : "text-terminal-text-secondary hover:text-terminal-text-primary"
              }`}
            >
              {t === "candlestick" ? "OHLC" : "Line"}
            </button>
          ))}
        </div>
      </div>

      {/* Period + indicators */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-2.5 py-1 text-xs font-mono rounded ${
                period === p
                  ? "bg-terminal-accent/20 text-terminal-accent"
                  : "text-terminal-text-secondary hover:text-terminal-text-primary"
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        <div className="h-4 w-px bg-terminal-border" />

        <div className="flex gap-1 flex-wrap">
          {INDICATORS.map((ind) => (
            <button
              key={ind.key}
              onClick={() => toggleIndicator(ind.key)}
              className={`px-2.5 py-1 text-xs font-mono rounded ${
                activeIndicators.includes(ind.key)
                  ? "bg-terminal-info/20 text-terminal-info"
                  : "text-terminal-text-secondary hover:text-terminal-text-primary"
              }`}
            >
              {ind.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart area */}
      {!selectedId ? (
        <div className="flex items-center justify-center h-[400px] border border-terminal-border rounded-md bg-terminal-bg-secondary">
          <p className="text-terminal-text-secondary">
            Select a security to view its chart.
          </p>
        </div>
      ) : loading && !chartData ? (
        <div className="animate-pulse h-[400px] bg-terminal-bg-secondary rounded-md" />
      ) : chartData && chartData.candles.length === 0 ? (
        <div className="flex items-center justify-center h-[400px] border border-terminal-border rounded-md bg-terminal-bg-secondary">
          <p className="text-terminal-text-secondary">
            No price data available for this period.
          </p>
        </div>
      ) : (
        <div className="border border-terminal-border rounded-md overflow-hidden">
          {chartData && (
            <div className="px-4 py-2 bg-terminal-bg-secondary border-b border-terminal-border flex items-center gap-4">
              <span className="font-mono font-semibold text-terminal-accent">
                {chartData.security.ticker}
              </span>
              <span className="text-sm text-terminal-text-secondary">
                {chartData.security.name}
              </span>
              {chartData.candles.length > 0 && (
                <>
                  <span className="font-mono text-sm">
                    {chartData.candles[
                      chartData.candles.length - 1
                    ].close.toFixed(2)}{" "}
                    {chartData.security.currency}
                  </span>
                  {chartData.candles.length >= 2 && (() => {
                    const last =
                      chartData.candles[chartData.candles.length - 1].close;
                    const prev =
                      chartData.candles[chartData.candles.length - 2].close;
                    const change = last - prev;
                    const changePct =
                      prev !== 0 ? ((change / prev) * 100).toFixed(2) : "0.00";
                    const color =
                      change > 0
                        ? "text-terminal-positive"
                        : change < 0
                        ? "text-terminal-negative"
                        : "text-terminal-text-tertiary";
                    return (
                      <span className={`font-mono text-sm ${color}`}>
                        {change > 0 ? "+" : ""}
                        {change.toFixed(2)} ({change > 0 ? "+" : ""}
                        {changePct}%)
                      </span>
                    );
                  })()}
                </>
              )}
              {loading && (
                <span className="text-xs text-terminal-text-tertiary ml-auto">
                  Loading...
                </span>
              )}
            </div>
          )}

          <div ref={chartContainerRef} />

          {activeIndicators.includes("rsi") && (
            <div className="border-t border-terminal-border">
              <div className="px-4 py-1 text-xs text-terminal-text-tertiary font-mono bg-terminal-bg-secondary">
                RSI (14)
              </div>
              <div ref={rsiContainerRef} />
            </div>
          )}

          {activeIndicators.includes("macd") && (
            <div className="border-t border-terminal-border">
              <div className="px-4 py-1 text-xs text-terminal-text-tertiary font-mono bg-terminal-bg-secondary">
                MACD (12, 26, 9)
              </div>
              <div ref={macdContainerRef} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ChartsPage() {
  return (
    <Suspense
      fallback={
        <div className="animate-pulse">
          <div className="h-8 bg-terminal-bg-secondary rounded w-48 mb-6" />
          <div className="h-[400px] bg-terminal-bg-secondary rounded" />
        </div>
      }
    >
      <ChartsContent />
    </Suspense>
  );
}
