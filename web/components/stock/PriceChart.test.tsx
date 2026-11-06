import { cleanup, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/lib/test-query";

const chart = vi.hoisted(() => ({
  options: [] as Array<Record<string, unknown>>,
  lines: [] as Array<{ price: number; title: string; lineStyle: number }>,
  candles: [] as Array<Record<string, unknown>>,
}));

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  CrosshairMode: { Normal: 0 },
  LineStyle: { Dashed: 2 },
  createChart: (_el: unknown, opts: Record<string, unknown>) => {
    chart.options.push(opts);
    const series = () => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
      createPriceLine: (l: { price: number; title: string; lineStyle: number }) => {
        chart.lines.push(l);
        return { applyOptions: vi.fn() };
      },
    });
    return {
      addCandlestickSeries: (o: Record<string, unknown>) => {
        chart.candles.push(o);
        return series();
      },
      addHistogramSeries: series,
      addLineSeries: series,
      priceScale: () => ({ applyOptions: vi.fn() }),
      timeScale: () => ({ fitContent: vi.fn() }),
      applyOptions: vi.fn(),
      remove: vi.fn(),
    };
  },
}));

import { PriceChart } from "./PriceChart";

const BARS = {
  as_of: "2026-11-05T21:00:00Z",
  bars: [
    { time: "2026-11-03", open: 180, high: 184, low: 179, close: 182.4, volume: 1000 },
    { time: "2026-11-04", open: 182.4, high: 186, low: 181, close: 185.1, volume: 1200 },
  ],
  sma50: [null, 178.2],
  sma200: [null, null],
};

beforeEach(() => {
  chart.options.length = 0;
  chart.lines.length = 0;
  chart.candles.length = 0;
});
afterEach(cleanup);

describe("PriceChart", () => {
  it("draws the caller's levels as dashed lines and names them in the chart's sentence", async () => {
    renderWithQuery(
      <PriceChart symbol="GOOGL" lines={[{ price: 215, title: "Fair value $215.00" }, { price: 190, title: "Entry ceiling $190.00" }]} />,
      { "/research/GOOGL/bars": BARS },
    );
    const img = await screen.findByRole("img");
    expect(img).toHaveAccessibleName(
      "GOOGL daily prices over the last year, from $182.40 to $185.10; Fair value $215.00; Entry ceiling $190.00",
    );
    expect(chart.lines.map((l) => [l.price, l.title, l.lineStyle])).toEqual([
      [215, "Fair value $215.00", 2],
      [190, "Entry ceiling $190.00", 2],
    ]);
    expect(screen.getByText(/Dashed lines are the value book's levels\./)).toBeInTheDocument();
  });

  it("draws candles by shape, not colour, with no logo on the canvas", async () => {
    renderWithQuery(<PriceChart symbol="GOOGL" />, { "/research/GOOGL/bars": BARS });
    await screen.findByRole("img");
    expect(chart.candles[0]?.upColor).toBe("transparent");
    expect((chart.options[0]?.layout as { attributionLogo?: boolean }).attributionLogo).toBe(false);
    expect(screen.getByText(/hollow on an up day, filled on a down day/)).toBeInTheDocument();
    expect(screen.queryByText(/Dashed lines/)).toBeNull();
  });

  it("says so in words when there is no history or the request fails", async () => {
    renderWithQuery(<PriceChart symbol="NEWCO" />, { "/research/NEWCO/bars": { ...BARS, bars: [], sma50: [], sma200: [] } });
    expect(await screen.findByText("No price history for NEWCO yet.")).toBeInTheDocument();
    cleanup();
    renderWithQuery(<PriceChart symbol="GONE" />, {});
    expect(await screen.findByText(/The price chart could not be loaded/)).toBeInTheDocument();
  });
});
