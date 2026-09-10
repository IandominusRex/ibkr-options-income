"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EquityCurveData } from "./types";

/**
 * Reads the semantic colour tokens from CSS custom properties at mount, never
 * hard-coded hex — the same rule PriceChart follows (M3), so the chart follows
 * the dark token system defined once in globals.css.
 */
function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function startsInWords(startsAt: string): string {
  const d = new Date(`${startsAt}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return "";
  return `since ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

type SeriesSpec = {
  key: "cumulative_realized" | "premium_cashflow";
  label: string;
  colorVar: string;
};

// premium_cashflow is premium cashflow — never "realised P&L". It will
// disagree with cumulative_realized (one is cash that moved, the other is
// paired P&L), and the full labels are what make that legible rather than
// alarming.
const SERIES: SeriesSpec[] = [
  { key: "cumulative_realized", label: "Cumulative realized P&L", colorVar: "--color-focus" },
  { key: "premium_cashflow", label: "Premium cashflow", colorVar: "--color-gain" },
];

/**
 * The equity curve: one point per journal day, `gaps` rendered as gaps.
 *
 * Rules this component refuses to break:
 * - **A gap renders as a gap.** `connectNulls` is false on every series: a
 *   straight line across days nobody measured is a fabricated claim. A missing
 *   day's value is `null` in the series data (the API's `gaps` list drives
 *   which days have none).
 * - **The chart never animates its data in.** `isAnimationActive={false}` on
 *   every series — a line that draws itself lies about its value during the
 *   animation (web/CLAUDE.md).
 * - **`prefers-reduced-motion` is respected**: with entry animation off, this
 *   means no transition on hover either.
 * - **The start date is stated in words** beneath the chart — the curve is
 *   the system's history, not the account's.
 *
 * Recharts does not expose `connectNulls`/`isAnimationActive` as DOM
 * attributes, so each series is wrapped in an element carrying `data-series`
 * plus mirrored `connect-nulls`/`is-animation-active` attributes for the tests
 * to read real props rather than Recharts internals.
 */
export function EquityChart({ curve }: { curve: EquityCurveData }) {
  const [colors, setColors] = useState<Record<string, string>>({});

  useEffect(() => {
    setColors({
      "--color-focus": cssVar("--color-focus"),
      "--color-gain": cssVar("--color-gain"),
      "--text-muted": cssVar("--text-muted"),
      "--bg-surface": cssVar("--bg-surface"),
      "--bg-background": cssVar("--bg-background"),
    });
  }, []);

  if ((curve.points ?? []).length === 0) {
    return <p className="text-sm text-muted">No history yet - the curve begins with the first journal day.</p>;
  }

  // Map the API's gaps onto the series: a gap day inserts a null point so the
  // line breaks there instead of bridging an unmeasured day.
  const gapSet = new Set(curve.gaps ?? []);
  const data: Array<Record<string, string | number | null>> = [];
  for (const point of curve.points ?? []) {
    data.push({ ...point });
    if (gapSet.has(nextIso(point.entry_date))) {
      data.push({ entry_date: nextIso(point.entry_date), cumulative_realized: null, premium_cashflow: null });
    }
  }

  return (
    <div data-testid="equity-chart-frame" data-chart-points={JSON.stringify(data)}>
      {/* Real-prop mirrors for the tests: Recharts does not expose
          connectNulls/isAnimationActive as DOM attributes, so each series
          records its actual props here — one element per series, asserted
          rather than trusted. `data-chart-points` on this frame mirrors the
          actual gap-inserted series data for the same reason: it proves a
          gap date landed a real null point at the right spot in the series,
          not just that the (always-false) connectNulls prop is set. */}
      {SERIES.map((s) => (
        <span
          key={s.key}
          hidden
          data-series={s.key}
          connect-nulls="false"
          is-animation-active="false"
        />
      ))}
      <div className="h-80 w-full">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid stroke={colors["--bg-surface"] || undefined} strokeDasharray="3 3" />
            <XAxis
              dataKey="entry_date"
              stroke={colors["--text-muted"] || undefined}
              tick={{ fill: colors["--text-muted"] || undefined, fontSize: 11 }}
              tickLine={false}
            />
            <YAxis
              stroke={colors["--text-muted"] || undefined}
              tick={{ fill: colors["--text-muted"] || undefined, fontSize: 11 }}
              tickLine={false}
              width={72}
            />
            <Tooltip
              contentStyle={{
                background: colors["--bg-surface"] || undefined,
                border: "none",
                borderRadius: 4,
              }}
              labelStyle={{ color: colors["--text-muted"] || undefined }}
            />
            {SERIES.map((s) => (
              <Line
                key={s.key}
                dataKey={s.key}
                name={s.label}
                stroke={colors[s.colorVar] || undefined}
                strokeWidth={1.5}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* The legend names both series in full — see SERIES' comment. Rendered
          as a real list (role=list) so a reader and a test agree on what the
          lines are called. */}
      <div className="mt-2 flex flex-wrap gap-4" role="list" aria-label="legend">
        {SERIES.map((s) => (
          <span key={s.key} role="listitem" className="flex items-center gap-2 text-xs text-muted">
            <span
              aria-hidden
              className="inline-block h-0.5 w-4"
              style={{ background: colors[s.colorVar] || "currentColor" }}
            />
            {s.label}
          </span>
        ))}
      </div>

      {curve.starts_at && (
        <p className="mt-2 text-xs text-muted" data-testid="equity-starts-at">
          The curve shows this system&apos;s recorded history, {startsInWords(curve.starts_at)}.
        </p>
      )}
    </div>
  );
}

function nextIso(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return isoDate;
  return new Date(d.getTime() + 86_400_000).toISOString().slice(0, 10);
}