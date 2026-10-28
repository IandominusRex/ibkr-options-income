"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money } from "./format";
import type { LedgerCurvePoint, LedgerMonth } from "./types";

// Charts never animate their data in (web/CLAUDE.md).

const BARS = [
  { label: "Premium", fill: "var(--color-focus)" },
  { label: "Realised", fill: "var(--color-gain)" },
];

export function PnlCurve({ points }: { points: LedgerCurvePoint[] }) {
  if (points.length === 0) return <p className="text-sm text-muted">No closed trades yet.</p>;
  return (
    <figure className="flex h-64 flex-col" aria-label="Cumulative realised P&L">
      <figcaption className="pb-2 text-sm text-muted">Cumulative realised P&L (USD)</figcaption>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points}>
            <CartesianGrid stroke="var(--color-border)" vertical={false} />
            <XAxis dataKey="point_date" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
            <YAxis tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={70} />
            <Tooltip formatter={(v) => money(Number(v))} />
            <Line type="stepAfter" dataKey="cumulative_usd" stroke="var(--chart-line)" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

export function MonthlyBars({ months }: { months: LedgerMonth[] }) {
  if (months.length === 0) return <p className="text-sm text-muted">No premium collected yet.</p>;
  return (
    <figure className="flex h-64 flex-col" aria-label="Monthly premium and realised P&L">
      <figcaption className="pb-2 text-sm text-muted">Premium collected vs realised, by month (USD)</figcaption>
      {/* The key names both bars in words: two colours alone would not say which is which. */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 pb-2" role="list" aria-label="legend">
        {BARS.map((b) => (
          <span key={b.label} role="listitem" className="flex items-center gap-2 text-[0.8125rem] text-muted">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: b.fill }} />
            {b.label}
          </span>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={months}>
            <CartesianGrid stroke="var(--color-border)" vertical={false} />
            <XAxis dataKey="month" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
            <YAxis tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={70} />
            <Tooltip formatter={(v) => money(Number(v))} />
            <Bar dataKey="premium_usd" name="Premium" fill={BARS[0].fill} isAnimationActive={false} />
            <Bar dataKey="realized_usd" name="Realised" fill={BARS[1].fill} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
