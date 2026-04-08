"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { apiGetRaw } from "@/lib/api";
import {
  createChart,
  type IChartApi,
  ColorType,
} from "lightweight-charts";

interface IndicatorValue {
  code: string;
  name: string;
  value: number;
  unit: string;
  date: string;
  change: number | null;
  frequency: string;
  region: string;
}

interface CategoryGroup {
  category: string;
  label: string;
  indicators: IndicatorValue[];
}

interface RegionData {
  region: string;
  regionLabel: string;
  categories: CategoryGroup[];
}

interface YieldPoint {
  tenor: string;
  code: string;
  yield: number;
  date?: string;
}

interface YieldCurveData {
  curve: string;
  curveLabel: string;
  current: YieldPoint[];
  comparisons: { label: string; points: { tenor: string; yield: number }[] }[];
}

interface SeriesPoint {
  time: string;
  value: number;
}

interface SeriesData {
  code: string;
  name: string;
  unit: string;
  category: string;
  region: string;
  points: SeriesPoint[];
}

import { InfoTip } from "@/components/ui/InfoTip";

// Descriptions for every macro indicator code
const INDICATOR_DESC: Record<string, string> = {
  // Finland
  FI_HICP: "Harmonised Index of Consumer Prices for Finland. ECB-comparable inflation measure used across the eurozone. Monthly, base year 2015 = 100.",
  FPCPITOTLZGFIN: "Finland consumer price inflation, year-over-year percentage change. Measures how fast prices are rising for Finnish consumers.",
  FI_UNEMP: "Finnish unemployment rate from ECB Labour Force Survey. Percentage of the labour force that is unemployed.",
  LRHUTTTTFIM156S: "Finland harmonised unemployment rate (OECD/FRED). Alternative source for Finnish unemployment data.",
  FI_GDP_YOY: "Finland real GDP growth, year-over-year. Measures the rate of economic expansion or contraction.",
  CLVMNACSCAB1GQFI: "Finland real GDP (chain-linked volumes, seasonally adjusted). FRED mirror of Eurostat national accounts data.",

  // Eurozone
  ECB_MRR: "ECB Main Refinancing Rate. The interest rate banks pay to borrow from the ECB for one week — the primary tool for eurozone monetary policy.",
  ECB_DFR: "ECB Deposit Facility Rate. The rate banks earn on overnight deposits at the ECB — sets the floor for short-term money market rates.",
  ECBMRRFR: "ECB Main Refinancing Rate (FRED mirror). Same as ECB_MRR, sourced from FRED.",
  ECBDFR: "ECB Deposit Facility Rate (FRED mirror). Same as ECB_DFR, sourced from FRED.",
  EZ_YC_2Y: "Eurozone AAA sovereign yield curve at 2-year maturity. Reflects short-term interest rate expectations and ECB policy outlook.",
  EZ_YC_5Y: "Eurozone AAA sovereign yield curve at 5-year maturity. Mid-curve benchmark for eurozone government borrowing costs.",
  EZ_YC_10Y: "Eurozone AAA sovereign yield curve at 10-year maturity. Key benchmark for long-term borrowing costs and mortgage rates.",
  EZ_YC_30Y: "Eurozone AAA sovereign yield curve at 30-year maturity. Reflects very long-term inflation expectations and term premium.",
  IRLTLT01DEM156N: "Germany 10-year government bond yield. Benchmark safe-haven rate for the eurozone, analogous to US 10Y Treasury.",
  EZ_HICP: "Eurozone Harmonised Index of Consumer Prices. The ECB's primary inflation gauge — their 2% target is based on this measure.",
  EZ_HICP_CORE: "Eurozone Core HICP (excluding energy and food). Shows underlying inflation trend without volatile components — what the ECB watches for rate decisions.",
  CP0000EZ19M086NEST: "Eurozone CPI from FRED (Eurostat source). All-items consumer price index for the euro area.",
  EZ_GDP_YOY: "Eurozone real GDP growth, year-over-year. Aggregate economic growth across all euro area member states.",
  CLVMNACSCAB1GQEA19: "Eurozone real GDP (chain-linked volumes, seasonally adjusted). FRED mirror of Eurostat data.",
  EZ_UNEMP: "Eurozone unemployment rate. Percentage of the labour force that is unemployed across the euro area.",
  LRHUTTTTEZM156S: "Eurozone harmonised unemployment rate (OECD/FRED). Alternative source for eurozone unemployment.",

  // United States
  FEDFUNDS: "Federal Funds Effective Rate. The actual overnight interbank lending rate — reflects where the Fed has set monetary policy.",
  DFF: "Federal Funds Daily Rate. Daily observation of the effective federal funds rate.",
  DGS2: "US 2-Year Treasury yield. Highly sensitive to Fed rate expectations — the market's best guess of near-term policy.",
  DGS5: "US 5-Year Treasury yield. Mid-curve benchmark balancing rate expectations and term premium.",
  DGS10: "US 10-Year Treasury yield. The single most important interest rate in global finance — drives mortgages, corporate bonds, and equity valuations.",
  DGS30: "US 30-Year Treasury yield. The long bond — reflects long-term inflation expectations and the term premium investors demand for duration risk.",
  T10Y2Y: "10Y-2Y Treasury spread. Classic yield curve slope indicator. Negative (inverted) readings have preceded every US recession since 1970.",
  T10Y3M: "10Y-3M Treasury spread. Alternative yield curve measure. The Fed's preferred recession predictor — more reliable than 10Y-2Y historically.",
  CPIAUCSL: "US Consumer Price Index (All Urban Consumers). The headline CPI number — measures average price changes for a basket of goods and services.",
  CPILFESL: "US Core CPI (excluding food and energy). Strips out volatile components to show the underlying inflation trend. The Fed watches this closely.",
  PCEPI: "Personal Consumption Expenditures Price Index. The Fed's officially preferred inflation measure — broader than CPI and accounts for substitution effects.",
  T5YIE: "5-Year Breakeven Inflation Rate. Market-implied inflation expectation derived from TIPS spread. What bond traders expect average inflation to be over the next 5 years.",
  T10YIE: "10-Year Breakeven Inflation Rate. Market-implied long-term inflation expectation. Key gauge of whether inflation expectations remain anchored.",
  GDP: "US Nominal GDP. Total value of goods and services produced, not adjusted for inflation.",
  GDPC1: "US Real GDP (inflation-adjusted). The primary measure of US economic output and growth.",
  UNRATE: "US Unemployment Rate. Percentage of the labour force actively seeking but unable to find work. A lagging indicator — rises after recessions have already started.",
  PAYEMS: "US Total Nonfarm Payrolls. Monthly count of employed workers excluding farms. The most-watched jobs number — drives market reactions on release day.",
  ICSA: "Initial Jobless Claims (weekly). Number of new unemployment insurance claims filed. A leading indicator — spikes signal deteriorating labour market conditions.",
  MANEMP: "US Manufacturing Employment. Jobs in the manufacturing sector. A cyclical indicator that tends to lead broader economic turns.",

  // Global / Credit
  BAMLH0A0HYM2: "ICE BofA US High Yield OAS (Option-Adjusted Spread). The extra yield investors demand over Treasuries for holding junk bonds. Spikes signal credit stress and risk aversion — a key fear gauge.",
  BAMLC0A0CM: "ICE BofA US Investment Grade OAS. Credit spread for high-quality corporate bonds. Lower and more stable than HY OAS — widens during financial stress.",
};

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

const CURVE_COLORS = ["#8B5CF6", "#3B82F6", "#F59E0B"];

const REGION_FLAGS: Record<string, string> = {
  fi: "FI",
  ez: "EU",
  us: "US",
  global: "GL",
};

// Key indicator charts shown prominently per region
const REGION_KEY_CHARTS: Record<string, { code: string; label: string }[]> = {
  fi: [
    { code: "FI_HICP", label: "Finland HICP" },
  ],
  ez: [
    { code: "EZ_HICP", label: "Eurozone HICP" },
    { code: "EZ_HICP_CORE", label: "Eurozone Core HICP" },
  ],
  us: [
    { code: "CPIAUCSL", label: "US CPI (All Urban)" },
    { code: "CPILFESL", label: "US Core CPI (ex Food & Energy)" },
    { code: "PCEPI", label: "US PCE Price Index" },
    { code: "T5YIE", label: "5Y Breakeven Inflation" },
    { code: "T10YIE", label: "10Y Breakeven Inflation" },
  ],
  global: [
    { code: "BAMLH0A0HYM2", label: "US HY OAS (Credit Spread)" },
    { code: "BAMLC0A0CM", label: "US IG OAS (Credit Spread)" },
  ],
};

function YieldCurveChart({ data }: { data: YieldCurveData }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data.current.length) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    const padding = { top: 30, right: 20, bottom: 40, left: 50 };
    const plotW = w - padding.left - padding.right;
    const plotH = h - padding.top - padding.bottom;

    const allYields = [
      ...data.current.map((p) => p.yield),
      ...data.comparisons.flatMap((c) => c.points.map((p) => p.yield)),
    ];
    const minY = Math.floor(Math.min(...allYields) * 2) / 2 - 0.5;
    const maxY = Math.ceil(Math.max(...allYields) * 2) / 2 + 0.5;

    const tenors = data.current.map((p) => p.tenor);
    const xScale = (i: number) => padding.left + (i / Math.max(tenors.length - 1, 1)) * plotW;
    const yScale = (v: number) =>
      padding.top + plotH - ((v - minY) / (maxY - minY)) * plotH;

    ctx.fillStyle = CHART_COLORS.bg;
    ctx.fillRect(0, 0, w, h);

    ctx.strokeStyle = CHART_COLORS.border;
    ctx.lineWidth = 1;
    const ySteps = 6;
    for (let i = 0; i <= ySteps; i++) {
      const yVal = minY + ((maxY - minY) * i) / ySteps;
      const y = yScale(yVal);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(w - padding.right, y);
      ctx.stroke();

      ctx.fillStyle = CHART_COLORS.text;
      ctx.font = "11px 'JetBrains Mono', monospace";
      ctx.textAlign = "right";
      ctx.fillText(`${yVal.toFixed(1)}%`, padding.left - 8, y + 4);
    }

    ctx.textAlign = "center";
    tenors.forEach((t, i) => {
      ctx.fillStyle = CHART_COLORS.text;
      ctx.fillText(t, xScale(i), h - padding.bottom + 20);
    });

    data.comparisons.forEach((comp, ci) => {
      const color = CURVE_COLORS[ci + 1] || CHART_COLORS.text;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      comp.points.forEach((p, i) => {
        const ti = tenors.indexOf(p.tenor);
        if (ti < 0) return;
        const x = xScale(ti);
        const y = yScale(p.yield);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    });

    ctx.strokeStyle = CURVE_COLORS[0];
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    data.current.forEach((p, i) => {
      const x = xScale(i);
      const y = yScale(p.yield);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    data.current.forEach((p, i) => {
      const x = xScale(i);
      const y = yScale(p.yield);
      ctx.fillStyle = CURVE_COLORS[0];
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = CHART_COLORS.text;
      ctx.font = "11px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(`${p.yield.toFixed(2)}%`, x, y - 10);
    });

    let legendX = padding.left;
    const legendY = 12;
    ctx.font = "11px 'JetBrains Mono', monospace";

    ctx.fillStyle = CURVE_COLORS[0];
    ctx.fillRect(legendX, legendY - 4, 12, 2);
    legendX += 16;
    ctx.fillStyle = CHART_COLORS.text;
    ctx.textAlign = "left";
    ctx.fillText("Current", legendX, legendY);
    legendX += 60;

    data.comparisons.forEach((comp, ci) => {
      const color = CURVE_COLORS[ci + 1] || CHART_COLORS.text;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(legendX, legendY - 3);
      ctx.lineTo(legendX + 12, legendY - 3);
      ctx.stroke();
      ctx.setLineDash([]);
      legendX += 16;
      ctx.fillStyle = CHART_COLORS.text;
      ctx.fillText(comp.label, legendX, legendY);
      legendX += 60;
    });
  }, [data]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full"
      style={{ height: 220 }}
    />
  );
}

function MiniChart({ code, period }: { code: string; period: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    let cancelled = false;

    const loadAndRender = async () => {
      try {
        const result = await apiGetRaw<{ data: SeriesData }>(
          `/macro/series/${code}?period=${period}`
        );
        const points = result.data.points;
        if (!points.length || !containerRef.current || cancelled) return;

        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }

        const chart = createChart(containerRef.current, {
          layout: {
            background: { type: ColorType.Solid, color: CHART_COLORS.bg },
            textColor: CHART_COLORS.text,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
          },
          grid: {
            vertLines: { color: CHART_COLORS.border },
            horzLines: { color: CHART_COLORS.border },
          },
          rightPriceScale: { borderColor: CHART_COLORS.border },
          timeScale: { borderColor: CHART_COLORS.border, timeVisible: false },
          width: containerRef.current.clientWidth,
          height: 180,
          crosshair: { mode: 0 },
        });
        chartRef.current = chart;

        const first = points[0].value;
        const last = points[points.length - 1].value;
        const color = last >= first ? CHART_COLORS.positive : CHART_COLORS.negative;

        const series = chart.addLineSeries({
          color,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
        });
        series.setData(points as Parameters<typeof series.setData>[0]);
        chart.timeScale().fitContent();
      } catch (e) {
        console.error(`Failed to load series ${code}:`, e);
      }
    };

    loadAndRender();

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      cancelled = true;
      window.removeEventListener("resize", handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [code, period]);

  return <div ref={containerRef} />;
}

function KeyChartPanel({ charts }: { charts: { code: string; label: string }[] }) {
  const [period, setPeriod] = useState("2Y");

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Key Indicators</h2>
        <div className="flex gap-1">
          {(["1Y", "2Y", "5Y", "MAX"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-2 py-0.5 text-xs font-mono rounded ${
                period === p
                  ? "bg-terminal-accent/20 text-terminal-accent"
                  : "text-terminal-text-secondary hover:text-terminal-text-primary"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {charts.map((c) => (
          <div
            key={c.code}
            className="bg-terminal-bg-secondary border border-terminal-border rounded-md overflow-hidden"
          >
            <div className="px-3 py-2 border-b border-terminal-border flex items-center gap-1">
              <span className="text-sm font-medium">{c.label}</span>
              {INDICATOR_DESC[c.code] && (
                <InfoTip text={INDICATOR_DESC[c.code]} />
              )}
              <span className="text-xs text-terminal-text-tertiary font-mono ml-auto">
                {c.code}
              </span>
            </div>
            <MiniChart code={c.code} period={period} />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function MacroPage() {
  const [regions, setRegions] = useState<RegionData[]>([]);
  const [usYieldCurve, setUsYieldCurve] = useState<YieldCurveData | null>(null);
  const [ezYieldCurve, setEzYieldCurve] = useState<YieldCurveData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeRegion, setActiveRegion] = useState<string>("fi");
  const [expandedChart, setExpandedChart] = useState<string | null>(null);
  const [chartPeriod, setChartPeriod] = useState("1Y");

  useEffect(() => {
    const load = async () => {
      try {
        const [sumResult, usYc, ezYc] = await Promise.all([
          apiGetRaw<{ data: RegionData[] }>("/macro/summary"),
          apiGetRaw<{ data: YieldCurveData }>("/macro/yield-curve?curve=us"),
          apiGetRaw<{ data: YieldCurveData }>("/macro/yield-curve?curve=ez"),
        ]);
        setRegions(sumResult.data);
        setUsYieldCurve(usYc.data);
        setEzYieldCurve(ezYc.data);
        // Default to first region that has data
        if (sumResult.data.length > 0) {
          setActiveRegion(sumResult.data[0].region);
        }
      } catch (e) {
        console.error("Failed to load macro data:", e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) {
    return (
      <div className="animate-pulse">
        <div className="h-8 bg-terminal-bg-secondary rounded w-48 mb-6" />
        <div className="grid grid-cols-2 gap-4 mb-6">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-24 bg-terminal-bg-secondary rounded" />
          ))}
        </div>
      </div>
    );
  }

  const activeData = regions.find((r) => r.region === activeRegion);
  const showUsYieldCurve = activeRegion === "us" && usYieldCurve && usYieldCurve.current.length > 0;
  const showEzYieldCurve = activeRegion === "ez" && ezYieldCurve && ezYieldCurve.current.length > 0;

  const formatValue = (ind: IndicatorValue) => {
    if (ind.unit === "%") return `${ind.value.toFixed(2)}%`;
    if (ind.unit === "index") return ind.value.toFixed(1);
    if (ind.unit === "B USD") return `$${(ind.value / 1000).toFixed(1)}T`;
    if (ind.unit === "M EUR") {
      if (ind.value >= 1_000_000) return `\u20AC${(ind.value / 1_000_000).toFixed(1)}T`;
      return `\u20AC${(ind.value / 1000).toFixed(0)}B`;
    }
    if (ind.unit === "K") return `${(ind.value / 1000).toFixed(1)}M`;
    if (ind.value >= 1_000_000) return `${(ind.value / 1000).toFixed(0)}K`;
    if (ind.value >= 1000) return `${(ind.value / 1000).toFixed(1)}K`;
    return ind.value.toFixed(2);
  };

  const formatChange = (ind: IndicatorValue) => {
    if (ind.change === null) return null;
    const sign = ind.change > 0 ? "+" : "";
    if (ind.unit === "%") return `${sign}${ind.change.toFixed(2)}pp`;
    if (ind.unit === "K") return `${sign}${ind.change.toFixed(0)}K`;
    if (ind.unit === "M EUR") return `${sign}${(ind.change / 1000).toFixed(1)}B`;
    return `${sign}${ind.change.toFixed(1)}`;
  };

  const changeColor = (change: number | null, code: string) => {
    if (change === null || change === 0) return "text-terminal-text-tertiary";
    // For unemployment, spreads, inflation — rising is usually bad
    const badIfUp = ["UNRATE", "EZ_UNEMP", "FI_UNEMP", "LRHUTTTTEZM156S", "LRHUTTTTFIM156S",
      "BAMLH0A0HYM2", "BAMLC0A0CM", "ICSA"];
    if (badIfUp.includes(code)) {
      return change > 0 ? "text-terminal-negative" : "text-terminal-positive";
    }
    return change > 0 ? "text-terminal-positive" : "text-terminal-negative";
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Macro Dashboard</h1>
      </div>

      {/* Region tabs */}
      <div className="flex gap-1 mb-6">
        {regions.map((r) => (
          <button
            key={r.region}
            onClick={() => {
              setActiveRegion(r.region);
              setExpandedChart(null);
            }}
            className={`px-4 py-2 text-sm font-mono rounded transition-colors ${
              activeRegion === r.region
                ? "bg-terminal-accent/20 text-terminal-accent"
                : "text-terminal-text-secondary hover:text-terminal-text-primary hover:bg-terminal-bg-secondary"
            }`}
          >
            <span className="mr-1.5 text-xs opacity-60">
              {REGION_FLAGS[r.region] || ""}
            </span>
            {r.regionLabel}
          </button>
        ))}
      </div>

      {/* Yield Curves */}
      {showUsYieldCurve && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">US Treasury Yield Curve</h2>
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
            <YieldCurveChart data={usYieldCurve!} />
            <YieldCurveFooter data={usYieldCurve!} />
          </div>
        </div>
      )}
      {showEzYieldCurve && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold mb-3">Euro AAA Sovereign Yield Curve</h2>
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-md p-4">
            <YieldCurveChart data={ezYieldCurve!} />
            <YieldCurveFooter data={ezYieldCurve!} />
          </div>
        </div>
      )}

      {/* Key indicator charts for active region */}
      {REGION_KEY_CHARTS[activeRegion] && (
        <KeyChartPanel charts={REGION_KEY_CHARTS[activeRegion]} />
      )}

      {/* Indicator categories for active region */}
      {activeData?.categories.map((cat) => (
        <div key={cat.category} className="mb-6">
          <h2 className="text-lg font-semibold mb-3">{cat.label}</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {cat.indicators.map((ind) => {
              const chgStr = formatChange(ind);
              const isExpanded = expandedChart === ind.code;
              return (
                <div
                  key={ind.code}
                  className={
                    isExpanded
                      ? "col-span-2 md:col-span-3 lg:col-span-4"
                      : ""
                  }
                >
                  <button
                    onClick={() =>
                      setExpandedChart(isExpanded ? null : ind.code)
                    }
                    className={`w-full text-left bg-terminal-bg-secondary border rounded-md p-3 transition-colors ${
                      isExpanded
                        ? "border-terminal-accent"
                        : "border-terminal-border hover:border-terminal-accent/50"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-1">
                      <div className="flex items-center gap-1 text-xs text-terminal-text-secondary font-mono">
                        {ind.name}
                        {INDICATOR_DESC[ind.code] && (
                          <InfoTip text={INDICATOR_DESC[ind.code]} />
                        )}
                      </div>
                      <div className="text-xs text-terminal-text-tertiary font-mono shrink-0">
                        {ind.code}
                      </div>
                    </div>
                    <div className="flex items-baseline gap-2 mt-1">
                      <div className="text-xl font-mono font-semibold">
                        {formatValue(ind)}
                      </div>
                      {chgStr && (
                        <div
                          className={`text-xs font-mono ${changeColor(
                            ind.change,
                            ind.code
                          )}`}
                        >
                          {chgStr}
                        </div>
                      )}
                    </div>
                    <div className="text-xs text-terminal-text-tertiary mt-1 font-mono">
                      {ind.date} · {ind.frequency}
                    </div>
                  </button>
                  {isExpanded && (
                    <div className="mt-2 bg-terminal-bg-secondary border border-terminal-border rounded-md overflow-hidden">
                      <div className="px-4 py-2 border-b border-terminal-border flex items-center gap-2">
                        <span className="text-sm font-medium">
                          {ind.name}
                        </span>
                        <span className="text-xs text-terminal-text-tertiary font-mono">
                          ({ind.code})
                        </span>
                        <div className="flex gap-1 ml-auto">
                          {(["3M", "6M", "1Y", "2Y", "5Y"] as const).map(
                            (p) => (
                              <button
                                key={p}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setChartPeriod(p);
                                }}
                                className={`px-2 py-0.5 text-xs font-mono rounded ${
                                  chartPeriod === p
                                    ? "bg-terminal-accent/20 text-terminal-accent"
                                    : "text-terminal-text-secondary hover:text-terminal-text-primary"
                                }`}
                              >
                                {p}
                              </button>
                            )
                          )}
                        </div>
                      </div>
                      <MiniChart code={ind.code} period={chartPeriod} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {!activeData && (
        <div className="flex items-center justify-center h-48 border border-terminal-border rounded-md bg-terminal-bg-secondary">
          <p className="text-terminal-text-secondary">
            No data available for this region. Run the pipelines to fetch data.
          </p>
        </div>
      )}
    </div>
  );
}

function YieldCurveFooter({ data }: { data: YieldCurveData }) {
  if (data.current.length < 2) return null;

  const short = data.current[0].yield;
  const long = data.current[data.current.length - 1].yield;
  const spread = long - short;
  const inverted = spread < 0;

  return (
    <div className="flex gap-6 mt-3 text-xs text-terminal-text-tertiary font-mono">
      <span
        className={
          inverted ? "text-terminal-negative" : "text-terminal-positive"
        }
      >
        {inverted ? "INVERTED" : "NORMAL"} —{" "}
        {data.current[data.current.length - 1].tenor}/
        {data.current[0].tenor} spread: {spread > 0 ? "+" : ""}
        {spread.toFixed(2)}pp
      </span>
      <span>As of {data.current[0].date}</span>
    </div>
  );
}
