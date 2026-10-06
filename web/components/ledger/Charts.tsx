"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money } from "./format";
import type { LedgerCurvePoint, LedgerMonth } from "./types";

// Charts never animate their data in (web/CLAUDE.md).

export function PnlCurve({ points }: { points: LedgerCurvePoint[] }) {
  if (points.length === 0) return <p className="text-sm text-muted">No closed trades yet.</p>;
  return (
    <figure className="h-64" aria-label="Cumulative realised P&L">
      <figcaption className="pb-2 text-sm text-muted">Cumulative realised P&L (USD)</figcaption>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <CartesianGrid stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="point_date" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
          <YAxis tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={70} />
          <Tooltip formatter={(v) => money(Number(v))} />
          <Line type="stepAfter" dataKey="cumulative_usd" stroke="var(--color-gain)" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  );
}

export function MonthlyBars({ months }: { months: LedgerMonth[] }) {
  if (months.length === 0) return <p className="text-sm text-muted">No premium collected yet.</p>;
  return (
    <figure className="h-64" aria-label="Monthly premium and realised P&L">
      <figcaption className="pb-2 text-sm text-muted">Premium collected vs realised, by month (USD)</figcaption>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={months}>
          <CartesianGrid stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="month" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
          <YAxis tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={70} />
          <Tooltip formatter={(v) => money(Number(v))} />
          <Bar dataKey="premium_usd" name="Premium" fill="var(--color-focus)" isAnimationActive={false} />
          <Bar dataKey="realized_usd" name="Realised" fill="var(--color-gain)" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}
