"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import {
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";

import { apiFetch } from "@/lib/api";

type Bar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type BarsResponse = {
  as_of: string;
  bars: Bar[];
  sma50: (number | null)[];
  sma200: (number | null)[];
};

/**
 * Reads the semantic colour tokens from CSS custom properties at mount, never hard-coded
 * hex. The chart draws to a canvas, so it needs resolved colour strings, not `var(...)"
 * references — but the tokens are defined globally in `globals.css` and this component only
 * mounts client-side, so the computed values are always present. An empty string means the
 * token was misconfigured; the chart renders with an empty series colour rather than a
 * hex the rest of the page does not use.
 */
function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function PriceChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const { data } = useQuery<BarsResponse>({
    queryKey: ["bars", symbol],
    queryFn: () => apiFetch<BarsResponse>(`/research/${symbol}/bars?range=1y`),
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const gain = cssVar("--color-gain");
    const loss = cssVar("--color-loss");
    const muted = cssVar("--text-muted");
    const background = cssVar("--bg-background");
    const surface = cssVar("--bg-surface");
    const focus = cssVar("--color-focus");

    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: background },
        textColor: muted,
        fontFamily: "var(--font-mono), ui-monospace, monospace",
      },
      grid: {
        vertLines: { color: surface },
        horzLines: { color: surface },
      },
      rightPriceScale: { borderColor: surface },
      timeScale: { borderColor: surface },
      crosshair: { mode: 0 },
      handleScale: false,
      handleScroll: false,
    });
    chartRef.current = chart;

    const candle = chart.addCandlestickSeries({
      upColor: gain,
      downColor: loss,
      wickUpColor: gain,
      wickDownColor: loss,
      borderVisible: false,
    });
    const volume = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    const sma50Line = chart.addLineSeries({
      color: focus,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const sma200Line = chart.addLineSeries({
      color: muted,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    if (data && data.bars.length > 0) {
      candle.setData(
        data.bars.map((b) => ({
          time: b.time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        })),
      );
      volume.setData(
        data.bars.map((b) => ({
          time: b.time,
          value: b.volume,
          color: b.close >= b.open ? gain : loss,
        })),
      );
      sma50Line.setData(
        data.sma50
          .map((v, i) => (v === null ? null : { time: data.bars[i].time, value: v }))
          .filter((p): p is { time: string; value: number } => p !== null),
      );
      sma200Line.setData(
        data.sma200
          .map((v, i) => (v === null ? null : { time: data.bars[i].time, value: v }))
          .filter((p): p is { time: string; value: number } => p !== null),
      );
      chart.timeScale().fitContent();
    }

    const resize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener("resize", resize);

    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
      chartRef.current = null;
    };
  }, [data]);

  return (
    <div className="overflow-x-auto rounded-md bg-surface">
      <div ref={containerRef} className="h-80 w-full" />
    </div>
  );
}