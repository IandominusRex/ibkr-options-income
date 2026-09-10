import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EquityChart } from "./EquityChart";
import type { EquityCurveData, EquityPointData } from "./types";

// Task 5.5 — the equity curve. Recharts does not expose connect-nulls or
// is-animation-active as DOM attributes, so the chart wraps each series in its
// own element carrying data-* attributes mirroring the real props — these
// assertions read those mirrors, not Recharts internals.

function aPoint(overrides: Partial<EquityPointData> = {}): EquityPointData {
  return {
    entry_date: "2026-09-01",
    net_liquidation: 250_000,
    unrealized_pnl: 100,
    cumulative_realized: 0,
    premium_cashflow: 42,
    ...overrides,
  };
}

function aCurve(overrides: Partial<EquityCurveData> = {}): EquityCurveData {
  return {
    points: [
      aPoint({ entry_date: "2026-09-01", cumulative_realized: 0 }),
      aPoint({ entry_date: "2026-09-02", cumulative_realized: 149 }),
    ],
    gaps: [],
    starts_at: "2026-09-01",
    ...overrides,
  };
}

function curveWithGap(): EquityCurveData {
  return {
    points: [
      aPoint({ entry_date: "2026-09-01", cumulative_realized: 0 }),
      // 2026-09-02 is deliberately missing — the day after 09-01, matching
      // `gaps` below, so the component's own nextIso(point.entry_date) test
      // actually fires and inserts a real null point there.
      aPoint({ entry_date: "2026-09-03", cumulative_realized: 200 }),
    ],
    gaps: ["2026-09-02"],
    starts_at: "2026-09-01",
  };
}

function chartPoints(container: HTMLElement): Array<Record<string, string | number | null>> {
  const frame = container.querySelector('[data-testid="equity-chart-frame"]');
  return JSON.parse(frame?.getAttribute("data-chart-points") ?? "[]");
}

describe("EquityChart", () => {
  it("does not connect across a gap", () => {
    const { container } = render(<EquityChart curve={curveWithGap()} />);
    const series = container.querySelectorAll('[data-series]');
    expect(series.length).toBeGreaterThan(0);
    for (const el of series) {
      expect(el.getAttribute("connect-nulls")).not.toBe("true");
    }
  });

  it("inserts a real null point at the gap date, between its real neighbours", () => {
    const { container } = render(<EquityChart curve={curveWithGap()} />);
    const points = chartPoints(container);
    expect(points.map((p) => p.entry_date)).toEqual(["2026-09-01", "2026-09-02", "2026-09-03"]);
    const gapPoint = points.find((p) => p.entry_date === "2026-09-02");
    expect(gapPoint).toEqual({
      entry_date: "2026-09-02",
      cumulative_realized: null,
      premium_cashflow: null,
    });
  });

  it("inserts nothing extra when the curve has no gaps", () => {
    const { container } = render(<EquityChart curve={aCurve()} />);
    const points = chartPoints(container);
    expect(points.map((p) => p.entry_date)).toEqual(["2026-09-01", "2026-09-02"]);
    expect(points.every((p) => p.cumulative_realized !== null)).toBe(true);
  });

  it("never animates its data in", () => {
    const { container } = render(<EquityChart curve={aCurve()} />);
    const series = container.querySelectorAll("[data-series]");
    expect(series.length).toBeGreaterThan(0);
    series.forEach((el) => {
      expect(el.getAttribute("is-animation-active")).not.toBe("true");
    });
  });

  it("labels premium cashflow as premium cashflow, never as realised", () => {
    render(<EquityChart curve={aCurve()} />);
    expect(screen.getByText(/premium cashflow/i)).toBeInTheDocument();
    const legend = screen.getByRole("list", { name: /legend/i });
    expect(within(legend).queryByText(/^realised p&l$/i)).toBeNull();
  });

  it("states when the curve begins", () => {
    render(<EquityChart curve={{ ...aCurve(), starts_at: "2026-03-02" }} />);
    expect(screen.getByText(/since 2 March 2026/i)).toBeInTheDocument();
  });

  it("names both series in full in the legend", () => {
    render(<EquityChart curve={aCurve()} />);
    const legend = screen.getByRole("list", { name: /legend/i });
    expect(within(legend).getByText(/cumulative realized/i)).toBeInTheDocument();
    expect(within(legend).getByText(/premium cashflow/i)).toBeInTheDocument();
  });

  it("renders one line of text, not an empty chart frame, for an empty curve", () => {
    render(<EquityChart curve={{ points: [], gaps: [], starts_at: null }} />);
    expect(screen.getByText(/no history yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("equity-chart-frame")).toBeNull();
  });
});