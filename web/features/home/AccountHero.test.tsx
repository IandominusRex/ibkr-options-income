import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery, apiFetchMock } from "@/lib/test-query";

const chart = vi.hoisted(() => ({
  handlers: [] as Array<(p: { time?: number }) => void>,
  /** every series.setData(...) argument, in call order */
  data: [] as Array<Array<{ time: number; value: number }>>,
  /** every createChart(...) options argument, in call order */
  options: [] as Array<{ layout?: { attributionLogo?: boolean } }>,
}));

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  CrosshairMode: { Magnet: 1 },
  LineType: { Simple: 0 },
  createChart: (_el: unknown, opts: { layout?: { attributionLogo?: boolean } }) => {
    chart.options.push(opts);
    return {
      addLineSeries: () => ({ setData: (d: Array<{ time: number; value: number }>) => chart.data.push(d), applyOptions: vi.fn() }),
      subscribeCrosshairMove: (h: (p: { time?: number }) => void) => chart.handlers.push(h),
      unsubscribeCrosshairMove: vi.fn(),
      timeScale: () => ({ fitContent: vi.fn() }),
      applyOptions: vi.fn(),
      remove: vi.fn(),
    };
  },
}));

import { AccountHero } from "./AccountHero";
import type { AccountValueResponse, RangeKey } from "./types";

const body = (range: RangeKey): AccountValueResponse => ({
  as_of: new Date().toISOString(),
  series: {
    range,
    points: [
      { at: "2026-10-12T20:00:00Z", value: 101_000 },
      { at: "2026-10-13T18:00:00Z", value: 101_500 },
    ],
    latest: 101_500,
    latest_at: "2026-10-13T18:00:00Z",
    previous_close: 101_000,
    change_today: 500,
    change_today_pct: 0.496,
    change: 500,
    change_pct: 0.496,
    change_since: "2026-10-12T20:00:00Z",
  },
});

describe("AccountHero", () => {
  it("shows the account value and today's signed change in words", async () => {
    renderWithQuery(<AccountHero />, { "/portfolio/value": body("1m") });
    expect(await screen.findByText("$101,500.00")).toBeInTheDocument();
    expect(screen.getByText("+$500.00 (0.50%) past month")).toBeInTheDocument();
  });
  it("rewrites the number while scrubbing and restores it after", async () => {
    renderWithQuery(<AccountHero />, { "/portfolio/value": body("1m") });
    await screen.findByText("$101,500.00");
    const t = Math.floor(Date.parse("2026-10-12T20:00:00Z") / 1000);
    act(() => chart.handlers.at(-1)!({ time: t }));
    expect(screen.getByText("$101,000.00")).toBeInTheDocument();
    act(() => chart.handlers.at(-1)!({}));
    expect(screen.getByText("$101,500.00")).toBeInTheDocument();
  });
  it("refetches for a new range", async () => {
    renderWithQuery(<AccountHero />, { "/portfolio/value": body("1m") });
    await screen.findByText("$101,500.00");
    fireEvent.click(screen.getByRole("button", { name: "3M" }));
    expect(apiFetchMock.mock.calls.some((c) => c[0] === "/portfolio/value?range=3m")).toBe(true);
  });
  it("can be scrubbed from the keyboard and restores on Escape", async () => {
    renderWithQuery(<AccountHero />, { "/portfolio/value": body("1m") });
    await screen.findByText("$101,500.00");
    const slider = screen.getByRole("slider", { name: /Account value history/ });
    expect(slider).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(slider, { key: "ArrowLeft" });
    expect(screen.getByText("$101,000.00")).toBeInTheDocument();
    expect(slider).toHaveAttribute("aria-valuenow", "0");
    expect(slider.getAttribute("aria-valuetext")).toContain("$101,000.00");
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(screen.getByText("$101,500.00")).toBeInTheDocument();
    fireEvent.keyDown(slider, { key: "Home" });
    expect(screen.getByText("$101,000.00")).toBeInTheDocument();
    fireEvent.keyDown(slider, { key: "Escape" });
    expect(screen.getByText("$101,500.00")).toBeInTheDocument();
  });
  it("leaves the keyboard scrub when the chart loses focus", async () => {
    renderWithQuery(<AccountHero />, { "/portfolio/value": body("1m") });
    await screen.findByText("$101,500.00");
    const slider = screen.getByRole("slider", { name: /Account value history/ });
    fireEvent.keyDown(slider, { key: "Home" });
    expect(screen.getByText("$101,000.00")).toBeInTheDocument();
    fireEvent.blur(slider);
    expect(screen.getByText("$101,500.00")).toBeInTheDocument();
  });
  it("shows neutral, not green, when the day's change is exactly zero", async () => {
    const flat = body("1m");
    flat.series = { ...flat.series, change: 0, change_pct: 0 };
    renderWithQuery(<AccountHero />, { "/portfolio/value": flat });
    const line = await screen.findByText("$0 (0.00%) past month");
    expect(line.className).not.toMatch(/text-gain|text-loss/);
  });
  it("keeps the value and says when it is from when today's change is unknown", async () => {
    const weekend = body("1m");
    weekend.series = { ...weekend.series, change: null, change_pct: null };
    renderWithQuery(<AccountHero />, { "/portfolio/value": weekend });
    expect(await screen.findByText("$101,500.00")).toBeInTheDocument();
    const line = screen.getByText(/last value Oct 13, 2026/);
    expect(line).toHaveTextContent("n/a past month · last value Oct 13, 2026");
    // Unknown carries the hatch as well as the word, here as everywhere (DESIGN.md Words First).
    expect(within(line).getByText("n/a")).toHaveClass("hatch");
  });
  describe("points the chart cannot take as they are", () => {
    // lightweight-charts wants strictly ascending whole-second times and throws on a tie.
    const at = (iso: string) => Math.floor(Date.parse(iso) / 1000);
    function withPoints(points: Array<{ at: string; value: number }>) {
      const b = body("1d");
      const last = points[points.length - 1];
      b.series = { ...b.series, points, latest: last.value, latest_at: last.at };
      return b;
    }
    const lastPlotted = () => chart.data[chart.data.length - 1];

    it("plots one point per second, the last one, so two snapshots in one second do not crash the chart", async () => {
      chart.data.length = 0;
      renderWithQuery(<AccountHero />, {
        "/portfolio/value": withPoints([
          { at: "2026-10-13T14:00:00.100Z", value: 100_000 },
          { at: "2026-10-13T14:00:00.900Z", value: 100_250 },
          { at: "2026-10-13T14:05:00Z", value: 100_500 },
        ]),
      });
      await screen.findByText("$100,500.00");
      expect(lastPlotted()).toEqual([
        { time: at("2026-10-13T14:00:00Z"), value: 100_250 },
        { time: at("2026-10-13T14:05:00Z"), value: 100_500 },
      ]);
    });
    it("hands the chart strictly ascending times however the rows arrive", async () => {
      chart.data.length = 0;
      renderWithQuery(<AccountHero />, {
        "/portfolio/value": withPoints([
          { at: "2026-10-13T14:10:00Z", value: 103 },
          { at: "2026-10-13T14:00:00.200Z", value: 101 },
          { at: "2026-10-13T14:00:00.700Z", value: 102 },
          { at: "2026-10-13T14:05:00Z", value: 104 },
          { at: "2026-10-13T14:10:00Z", value: 105 },
        ]),
      });
      await screen.findByText("$105.00");
      const times = lastPlotted().map((p) => p.time);
      expect(times).toEqual([...times].sort((a, b) => a - b));
      expect(new Set(times).size).toBe(times.length);
      expect(lastPlotted().map((p) => p.value)).toEqual([102, 104, 105]);
    });
    it("a scrub on a merged second reads the point that was plotted", async () => {
      chart.data.length = 0;
      renderWithQuery(<AccountHero />, {
        "/portfolio/value": withPoints([
          { at: "2026-10-13T14:00:00.100Z", value: 100_000 },
          { at: "2026-10-13T14:00:00.900Z", value: 100_250 },
          { at: "2026-10-13T14:05:00Z", value: 100_500 },
        ]),
      });
      await screen.findByText("$100,500.00");
      act(() => chart.handlers.at(-1)!({ time: at("2026-10-13T14:00:00Z") }));
      expect(screen.getByText("$100,250.00")).toBeInTheDocument();
    });
    it("the keyboard steps through the plotted points, never onto one that was merged away", async () => {
      chart.data.length = 0;
      renderWithQuery(<AccountHero />, {
        "/portfolio/value": withPoints([
          { at: "2026-10-13T14:00:00.100Z", value: 100_000 },
          { at: "2026-10-13T14:00:00.900Z", value: 100_250 },
          { at: "2026-10-13T14:05:00Z", value: 100_500 },
        ]),
      });
      await screen.findByText("$100,500.00");
      const slider = screen.getByRole("slider", { name: /Account value history/ });
      expect(slider).toHaveAttribute("aria-valuemax", "1");
      fireEvent.keyDown(slider, { key: "ArrowLeft" });
      expect(screen.getByText("$100,250.00")).toBeInTheDocument();
      expect(slider).toHaveAttribute("aria-valuenow", "0");
      fireEvent.keyDown(slider, { key: "ArrowLeft" });
      expect(screen.getByText("$100,250.00")).toBeInTheDocument();
      expect(screen.queryByText("$100,000.00")).toBeNull();
    });
  });
  it("ends the range row with the calendar button, and credits TradingView nowhere on the chart", async () => {
    // The licence link moved to More (Credits). The chart's own logo stays off so nothing sits on the line.
    renderWithQuery(<AccountHero />, { "/portfolio/value": body("1m") });
    const button = await screen.findByRole("button", { name: "Daily realised P&L calendar" });
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    expect(screen.queryByText(/TradingView/)).toBeNull();
    expect(screen.queryByRole("link", { name: /TradingView/ })).toBeNull();
    expect(chart.options.at(-1)?.layout?.attributionLogo).toBe(false);
  });
  // Final review m5: a stale headline during market hours carries the positions card's flag
  // word and its age; a legitimate last close (after 16:00 ET, a weekend) does not.
  describe("the Delayed flag", () => {
    const stale = () => {
      const b = body("1d");
      b.series = { ...b.series, latest_at: "2026-10-13T15:00:00Z" }; // 11:00 ET, Tue Oct 13
      return b;
    };
    it("flags a headline older than 30 minutes during market hours, with its age, in words", async () => {
      renderWithQuery(<AccountHero now={new Date("2026-10-13T19:00:00Z")} />, { "/portfolio/value": stale() });
      const word = await screen.findByText("Delayed");
      expect(word).toHaveAttribute("data-tone", "flag");
      expect(word).toHaveClass("bg-flag", "text-on-flag");
      expect(screen.getByText("4h ago")).toBeInTheDocument();
      // The value itself stays: the flag says how old it is, it does not hide it.
      expect(screen.getByText("$101,500.00")).toBeInTheDocument();
    });
    it("does not flag a fresh headline", async () => {
      renderWithQuery(<AccountHero now={new Date("2026-10-13T15:10:00Z")} />, { "/portfolio/value": stale() });
      await screen.findByText("$101,500.00");
      expect(screen.queryByText("Delayed")).toBeNull();
    });
    it("does not flag the last close after 16:00 New York time", async () => {
      const close = body("1d");
      close.series = { ...close.series, latest_at: "2026-10-13T20:00:00Z" };
      renderWithQuery(<AccountHero now={new Date("2026-10-13T23:30:00Z")} />, { "/portfolio/value": close });
      await screen.findByText("$101,500.00");
      expect(screen.queryByText("Delayed")).toBeNull();
    });
    it("does not flag Friday's close at a weekend", async () => {
      const friday = body("1d");
      friday.series = { ...friday.series, latest_at: "2026-10-16T20:00:00Z", change: null, change_pct: null };
      renderWithQuery(<AccountHero now={new Date("2026-10-17T16:00:00Z")} />, { "/portfolio/value": friday });
      await screen.findByText("$101,500.00");
      expect(screen.queryByText("Delayed")).toBeNull();
    });
    it("renders without a flag when the headline time is unknown", async () => {
      const unknown = body("1d");
      unknown.series = { ...unknown.series, latest_at: null };
      renderWithQuery(<AccountHero now={new Date("2026-10-13T19:00:00Z")} />, { "/portfolio/value": unknown });
      expect(await screen.findByText("$101,500.00")).toBeInTheDocument();
      expect(screen.queryByText("Delayed")).toBeNull();
    });
  });
  it("says there is no history yet instead of drawing an empty frame", async () => {
    const empty = body("1m");
    empty.series = { ...empty.series, points: [], latest: null, change: null, change_pct: null };
    renderWithQuery(<AccountHero />, { "/portfolio/value": empty });
    expect(await screen.findByText("No account history yet.")).toBeInTheDocument();
    // The value and the day's change are both unknown, and both say so with the hatch.
    const unknowns = screen.getAllByText("n/a");
    expect(unknowns).toHaveLength(2);
    for (const u of unknowns) expect(u).toHaveClass("hatch");
  });
});
