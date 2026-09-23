"use client";

import { useEffect, useId, useMemo, useState, type PointerEvent } from "react";
import type { PriceHistoryRange, PriceSnapshot } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";

type RangeKey = PriceHistoryRange;
type ChartPoint = { price: number; timestamp: number };
type CacheEntry = { expiresAt: number; promise: Promise<PriceSnapshot[]> };

const HISTORY_CACHE_TTL = 60_000;
const historyCache = new Map<string, CacheEntry>();
const emptyHistory: PriceSnapshot[] = [];

function cacheKey(instrumentId: string, range: RangeKey) {
  return `${instrumentId}:${range}`;
}

function primeHistoryCache(instrumentId: string, range: RangeKey, history: PriceSnapshot[]) {
  historyCache.set(cacheKey(instrumentId, range), {
    expiresAt: Date.now() + HISTORY_CACHE_TTL,
    promise: Promise.resolve(history),
  });
}

function fetchHistory(instrumentId: string, range: RangeKey): Promise<PriceSnapshot[]> {
  const key = cacheKey(instrumentId, range);
  const cached = historyCache.get(key);
  if (cached && cached.expiresAt > Date.now()) return cached.promise;

  const promise = fetch(
    `/api/instruments/${encodeURIComponent(instrumentId)}/price-history?range=${range}`,
  ).then(async (response) => {
    if (!response.ok) throw new Error(`Price history request failed (${response.status})`);
    return response.json() as Promise<PriceSnapshot[]>;
  }).catch((error: unknown) => {
    historyCache.delete(key);
    throw error;
  });

  historyCache.set(key, { expiresAt: Date.now() + HISTORY_CACHE_TTL, promise });
  return promise;
}

const ranges: { key: RangeKey; duration: number | null }[] = [
  { key: "1D", duration: 24 * 60 * 60 * 1_000 },
  { key: "1W", duration: 7 * 24 * 60 * 60 * 1_000 },
  { key: "1M", duration: 30 * 24 * 60 * 60 * 1_000 },
  { key: "3M", duration: 90 * 24 * 60 * 60 * 1_000 },
  { key: "1Y", duration: 365 * 24 * 60 * 60 * 1_000 },
  { key: "ALL", duration: null },
];
const dateTimeOptions = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Dublin" } as const;
const dateOptions = { day: "numeric", month: "short", timeZone: "Europe/Dublin" } as const;

function makeSeries(
  history: PriceSnapshot[],
  currentPrice: number,
  currentTimestamp: string,
): ChartPoint[] {
  const ordered = [...history].sort((a, b) => a.captured_at.localeCompare(b.captured_at));
  if (ordered.length === 0) {
    return [{ price: currentPrice, timestamp: new Date(currentTimestamp).getTime() }];
  }

  const firstTime = new Date(ordered[0].captured_at).getTime();
  return [
    { price: Number(ordered[0].old_price), timestamp: firstTime - 1 },
    ...ordered.map((snapshot) => ({
      price: Number(snapshot.new_price),
      timestamp: new Date(snapshot.captured_at).getTime(),
    })),
  ].filter((point) => Number.isFinite(point.price) && Number.isFinite(point.timestamp));
}

function rangeSeries(series: ChartPoint[], duration: number | null): ChartPoint[] {
  if (duration === null || series.length < 2) return series;
  const cutoff = series.at(-1)!.timestamp - duration;
  const firstVisible = series.findIndex((point) => point.timestamp >= cutoff);
  if (firstVisible <= 0) return series;
  return [
    { price: series[firstVisible - 1].price, timestamp: cutoff },
    ...series.slice(firstVisible),
  ];
}

export function PriceChart({
  instrumentId,
  history,
  currentPrice,
  currentTimestamp,
}: {
  instrumentId: string;
  history: PriceSnapshot[];
  currentPrice: number;
  currentTimestamp: string;
}) {
  const [selectedRange, setSelectedRange] = useState<RangeKey>("1W");
  const [historyByRange, setHistoryByRange] = useState<Partial<Record<RangeKey, PriceSnapshot[]>>>({
    "1W": history,
  });
  const [loadingRange, setLoadingRange] = useState<RangeKey | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const gradientId = useId().replaceAll(":", "");
  const selectedHistory = historyByRange[selectedRange] ?? emptyHistory;
  const allPoints = useMemo(
    () => makeSeries(selectedHistory, currentPrice, currentTimestamp),
    [selectedHistory, currentPrice, currentTimestamp],
  );
  const duration = ranges.find((range) => range.key === selectedRange)?.duration ?? null;
  const points = useMemo(() => rangeSeries(allPoints, duration), [allPoints, duration]);

  const width = 1000;
  const height = 330;
  const inset = { top: 24, right: 20, bottom: 30, left: 76 };
  const prices = points.map((point) => point.price);
  const dataMin = Math.min(...prices);
  const dataMax = Math.max(...prices);
  const padding = Math.max((dataMax - dataMin) * 0.12, dataMax * 0.01, 0.05);
  const minimum = dataMin - padding;
  const maximum = dataMax + padding;
  const range = maximum - minimum || 1;
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  const firstTimestamp = points[0]?.timestamp ?? 0;
  const lastTimestamp = points.at(-1)?.timestamp ?? firstTimestamp;
  const elapsed = Math.max(1, lastTimestamp - firstTimestamp);
  const chartPoints = points.map((point) => ({
    ...point,
    x: inset.left + (points.length === 1 ? plotWidth : ((point.timestamp - firstTimestamp) / elapsed) * plotWidth),
    y: inset.top + (1 - (point.price - minimum) / range) * plotHeight,
  }));
  const line = chartPoints.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const area = `${inset.left},${height - inset.bottom} ${line} ${width - inset.right},${height - inset.bottom}`;
  const startPrice = points[0]?.price ?? currentPrice;
  const endPrice = points.at(-1)?.price ?? currentPrice;
  const selectedChange = startPrice > 0 ? ((endPrice - startPrice) / startPrice) * 100 : 0;
  const positive = selectedChange >= 0;
  const activePoint = chartPoints[hoveredIndex ?? chartPoints.length - 1];

  useEffect(() => {
    primeHistoryCache(instrumentId, "1W", history);
  }, [history, instrumentId]);

  function selectRange(nextRange: RangeKey) {
    setSelectedRange(nextRange);
    setHoveredIndex(null);
    setLoadError(null);
    if (historyByRange[nextRange]) return;

    setLoadingRange(nextRange);
    void fetchHistory(instrumentId, nextRange)
      .then((nextHistory) => {
        setHistoryByRange((loaded) => ({ ...loaded, [nextRange]: nextHistory }));
      })
      .catch(() => {
        setLoadError(`Could not load the ${nextRange} price history. Try again.`);
      })
      .finally(() => {
        setLoadingRange((loading) => loading === nextRange ? null : loading);
      });
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const pointerX = ((event.clientX - bounds.left) / bounds.width) * width;
    const nearestIndex = chartPoints.reduce((nearest, point, index) => (
      Math.abs(point.x - pointerX) < Math.abs(chartPoints[nearest].x - pointerX) ? index : nearest
    ), 0);
    setHoveredIndex(nearestIndex);
  }

  return (
    <div>
      <div className="flex min-h-12 items-start justify-between gap-4 px-4 pt-4 md:px-5">
        <div>
          <strong className={`block text-sm font-semibold tabular-nums slashed-zero ${positive ? "text-[#35d07f]" : "text-[#f16d73]"}`}>
            {formatCurrency(endPrice - startPrice)} · {formatPercent(selectedChange)}
          </strong>
          <span className="mt-1 block text-[11px] font-medium text-[#77818e]">Across the selected {selectedRange.toLowerCase()} range</span>
        </div>
        {activePoint && (
          <p className="text-right text-[11px] leading-5 text-[#77818e]" aria-live="polite">
            <strong className="block text-sm font-semibold text-white tabular-nums slashed-zero">{formatCurrency(activePoint.price)}</strong>
            {new Date(activePoint.timestamp).toLocaleString("en-GB", dateTimeOptions)}
          </p>
        )}
      </div>

      <div className="relative">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`${selectedRange} price chart. Opened at ${formatCurrency(startPrice)} and closed at ${formatCurrency(endPrice)}.`}
          className={`mt-1 h-[250px] w-full touch-none md:h-[360px] ${positive ? "text-[#35d07f]" : "text-[#f16d73]"}`}
          onPointerMove={handlePointerMove}
          onPointerLeave={() => setHoveredIndex(null)}
        >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.22" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        {Array.from({ length: 5 }, (_, index) => {
          const y = inset.top + (index / 4) * plotHeight;
          const price = maximum - (index / 4) * range;
          return (
            <g key={index}>
              <line x1={inset.left} x2={width - inset.right} y1={y} y2={y} stroke="#222a35" strokeWidth="1" vectorEffect="non-scaling-stroke" />
              <text x={inset.left - 12} y={y + 4} fill="#818b97" textAnchor="end" className="text-[34px] sm:text-xl lg:text-xs">{formatCurrency(price)}</text>
            </g>
          );
        })}
        <g key={selectedRange} className="animate-[price-draw_360ms_cubic-bezier(0.16,1,0.3,1)] motion-reduce:animate-none">
          <polygon points={area} fill={`url(#${gradientId})`} />
          <polyline points={line} fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </g>
        {activePoint && (
          <g>
            <line x1={activePoint.x} x2={activePoint.x} y1={inset.top} y2={height - inset.bottom} stroke="#8fb5ff" strokeWidth="1" strokeDasharray="4 5" vectorEffect="non-scaling-stroke" />
            <circle cx={activePoint.x} cy={activePoint.y} r="5" fill="#080b10" stroke="currentColor" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
          </g>
        )}
        <text x={inset.left} y={height - 5} fill="#818b97" className="text-[34px] sm:text-xl lg:text-xs">{new Date(firstTimestamp).toLocaleDateString("en-GB", dateOptions)}</text>
        <text x={width - inset.right} y={height - 5} fill="#818b97" textAnchor="end" className="text-[34px] sm:text-xl lg:text-xs">{new Date(lastTimestamp).toLocaleDateString("en-GB", dateOptions)}</text>
        </svg>
        {loadingRange === selectedRange && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#0b0f15]/65 text-xs font-semibold text-[#aab3bf]" role="status">
            Loading {selectedRange} history…
          </div>
        )}
      </div>

      {loadError && <p className="px-4 pb-2 text-xs text-[#f16d73] md:px-5" role="alert">{loadError}</p>}

      <label className="mx-4 mb-3 flex items-center gap-3 text-[11px] font-medium text-[#818b97] md:mx-5">
        <span className="shrink-0">Explore price points</span>
        <input
          type="range"
          min="0"
          max={Math.max(0, chartPoints.length - 1)}
          value={hoveredIndex ?? Math.max(0, chartPoints.length - 1)}
          onChange={(event) => setHoveredIndex(Number(event.currentTarget.value))}
          aria-valuetext={activePoint ? `${formatCurrency(activePoint.price)} on ${new Date(activePoint.timestamp).toLocaleString("en-GB", { timeZone: "Europe/Dublin" })}` : undefined}
          className="h-4 min-w-0 flex-1 accent-[#8fb5ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]"
        />
      </label>

      <div className="flex items-center gap-1 border-t border-[#202630] px-3 py-2 md:px-5" aria-label="Chart range">
        {ranges.map((rangeOption) => (
          <button
            key={rangeOption.key}
            type="button"
            aria-pressed={selectedRange === rangeOption.key}
            onClick={() => selectRange(rangeOption.key)}
            className={`h-8 min-w-10 rounded-md px-3 text-[11px] font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] ${selectedRange === rangeOption.key ? "bg-[#8fb5ff] text-[#080b10]" : "text-[#7f8995] hover:bg-white/[0.04] hover:text-white"}`}
          >
            {rangeOption.key}
          </button>
        ))}
      </div>
    </div>
  );
}
