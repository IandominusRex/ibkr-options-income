"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { ColorType, CrosshairMode, LineStyle, createChart, type AutoscaleInfo, type IChartApi } from "lightweight-charts";
import { apiFetch } from "@/lib/api";
import { formatMoneyCell } from "@/lib/money";

type Bar = { time: string; open: number; high: number; low: number; close: number; volume: number };
type BarsResponse = { as_of: string; bars: Bar[]; sma50: (number | null)[]; sma200: (number | null)[] };
export type PriceLine = { price: number; title: string };

/** A resolved token colour for the canvas (it cannot read `var(...)`); empty when unset. */
function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function overlay(values: (number | null)[], bars: Bar[]) {
  return values
    .map((v, i) => (v === null || !bars[i] ? null : { time: bars[i].time, value: v }))
    .filter((p): p is { time: string; value: number } => p !== null);
}

/**
 * A year of daily candles in ink (an up day hollow, a down day filled: direction by shape, never by
 * colour), volume as light bars along the foot (the perforation tone), the 50-day average as a thin ink line and the 200-day
 * as a thin muted one, and the caller's levels as dashed rules with their labels on the price axis
 * (web overhaul Part 5: the value book's fair value, entry ceiling, half sale and stop). Colours come
 * from the tokens at mount and again when the theme changes; nothing animates in. The canvas is
 * hidden from a screen reader and a sentence stands in for it; a line of words under it names
 * every series.
 */
export function PriceChart({ symbol, lines = [] }: { symbol: string; lines?: PriceLine[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const { data, isError } = useQuery<BarsResponse>({
    queryKey: ["bars", symbol],
    queryFn: () => apiFetch<BarsResponse>(`/research/${symbol}/bars?range=1y`),
  });
  const bars = data?.bars ?? [];
  const lineKey = lines.map((l) => `${l.price}:${l.title}`).join("|");

  useEffect(() => {
    const el = ref.current;
    if (!el || !data || data.bars.length === 0) return;
    const ink = () => cssVar("--chart-line");
    const muted = () => cssVar("--text-muted");
    const light = () => cssVar("--color-perforation");
    const chart: IChartApi = createChart(el, {
      autoSize: true,
      height: 280,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: muted(),
        fontFamily: "var(--font-sans), system-ui, sans-serif",
        // The licence link is the Credits card on More; the logo would sit on the candles.
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.24 } },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Normal },
      handleScale: false,
      handleScroll: false,
    });
    const candles = chart.addCandlestickSeries({
      upColor: "transparent",
      downColor: ink(),
      borderUpColor: ink(),
      borderDownColor: ink(),
      wickUpColor: ink(),
      wickDownColor: ink(),
      priceLineVisible: false,
      lastValueVisible: true,
      // Price lines stay out of the autoscale range, so a level far from the year's bars (a fair value
      // 40% above the price) would fall off the canvas; widen the scale to take every named level in.
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const base = original();
        if (base === null || lines.length === 0) return base;
        const prices = lines.map((l) => l.price).filter((p) => Number.isFinite(p));
        return {
          ...base,
          priceRange: {
            minValue: Math.min(base.priceRange.minValue, ...prices),
            maxValue: Math.max(base.priceRange.maxValue, ...prices),
          },
        };
      },
    });
    candles.setData(data.bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    const volume = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      color: light(),
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });
    volume.setData(data.bars.map((b) => ({ time: b.time, value: b.volume })));
    const sma50 = chart.addLineSeries({ color: ink(), lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    sma50.setData(overlay(data.sma50, data.bars));
    const sma200 = chart.addLineSeries({ color: muted(), lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    sma200.setData(overlay(data.sma200, data.bars));
    const priceLines = lines.map((l) =>
      candles.createPriceLine({
        price: l.price,
        color: muted(),
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: l.title,
      }),
    );
    chart.timeScale().fitContent();

    const observer = new MutationObserver(() => {
      candles.applyOptions({ downColor: ink(), borderUpColor: ink(), borderDownColor: ink(), wickUpColor: ink(), wickDownColor: ink() });
      volume.applyOptions({ color: light() });
      sma50.applyOptions({ color: ink() });
      sma200.applyOptions({ color: muted() });
      chart.applyOptions({ layout: { textColor: muted() } });
      priceLines.forEach((pl) => pl.applyOptions({ color: muted() }));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      observer.disconnect();
      chart.remove();
    };
    // `lines` is compared by value through lineKey: a new array with the same levels must not rebuild the chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, lineKey]);

  if (isError && !data) {
    return <p className="text-sm text-muted">The price chart could not be loaded. It tries again when you reopen this page.</p>;
  }
  if (!data) {
    return <div role="status" aria-busy="true" aria-label="Loading the price chart" className="h-[280px] rounded-xl bg-sunk" />;
  }
  if (bars.length === 0) {
    return <p className="text-sm text-muted">{`No price history for ${symbol} yet.`}</p>;
  }
  const first = bars[0];
  const last = bars[bars.length - 1];
  return (
    <div>
      <div
        role="img"
        aria-label={`${symbol} daily prices over the last year, from ${formatMoneyCell(first.close)} to ${formatMoneyCell(last.close)}${lines.map((l) => `; ${l.title}`).join("")}`}
      >
        <div ref={ref} className="h-[280px] w-full" aria-hidden="true" />
      </div>
      <p className="mt-2 text-[0.8125rem] text-muted">
        One year of daily candles: hollow on an up day, filled on a down day. The ink line is the 50-day average, the grey
        line the 200-day, and the light bars are each day&apos;s volume.
        {lines.length > 0 ? " Dashed lines are the value book's levels." : ""}
      </p>
    </div>
  );
}
