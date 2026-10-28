import type { OptionLeg, PositionGroupData } from "@/components/portfolio/types";
import { type PositionRow, buildPositionRows, matchesQuery } from "@/features/home/positions";
import type { SpreadPosition } from "@/features/home/types";
import { formatMoneyCell } from "@/lib/money";
import { STRATEGY_LABEL } from "@/lib/strategy";

export type PositionsFilter = "all" | "csp" | "cc" | "spread" | "shares";

export const FILTERS: PositionsFilter[] = ["all", "csp", "cc", "spread", "shares"];
export const FILTER_LABEL: Record<PositionsFilter, string> = { ...STRATEGY_LABEL, shares: "Shares" };
export const EMPTY: Record<PositionsFilter, string> = {
  all: "No open positions.",
  csp: "No cash-secured puts open.",
  cc: "No covered calls open.",
  spread: "No credit spreads open.",
  shares: "No shares held.",
};

export type DetailPart = { label: string; value: string | null };

/** The figures under an option row: delta (and where it came from), the mark and the value. Null is unknown, never 0. */
export function legDetail(o: OptionLeg): DetailPart[] {
  const money = (v: number | null | undefined) => (v === null || v === undefined ? null : formatMoneyCell(v));
  const delta =
    o.delta === null || o.delta === undefined
      ? null
      : `${o.delta.toFixed(2)}${o.delta_source ? ` (${o.delta_source})` : ""}`;
  return [
    { label: "delta", value: delta },
    { label: "mark", value: money(o.market_price) },
    { label: "value", value: money(o.market_value) },
  ];
}

/**
 * A name's open P&L: its rows' own figures added up, but only when every one is known. A missing
 * figure makes the total unknown, never the sum of the rest and never $0; a card with no rows has
 * nothing to add up and is unknown too.
 */
export function rowsPnl(rows: PositionRow[]): number | null {
  const pnl = rows.filter((r) => r.valueLabel === "open P&L");
  if (pnl.length === 0 || pnl.some((r) => r.value === null)) return null;
  return pnl.reduce((sum, r) => sum + (r.value as number), 0);
}

export type NameCard = {
  underlying: string;
  rows: PositionRow[];
  /** The figure line under each option row, by row key. */
  details: Record<string, DetailPart[]>;
};

/** One card per underlying, alphabetical: Home's rows for the name, and each option's figures. */
export function buildNameCards(
  groups: PositionGroupData[],
  todayIso: string,
  alerted: ReadonlySet<string> = new Set(),
): NameCard[] {
  return groups
    .map((g) => ({
      underlying: g.underlying,
      rows: buildPositionRows([g], [], todayIso, "SPY", alerted),
      details: Object.fromEntries(g.options.map((o) => [`${g.underlying}:${o.symbol}`, legDetail(o)])),
    }))
    .filter((c) => c.rows.length > 0)
    .sort((a, b) => a.underlying.localeCompare(b.underlying));
}

export function spreadRows(spreads: SpreadPosition[], todayIso: string, underlying: string): PositionRow[] {
  return buildPositionRows([], spreads, todayIso, underlying);
}

/** The rows the chosen type and the search leave in. */
export function narrowRows(rows: PositionRow[], filter: PositionsFilter, query: string): PositionRow[] {
  return rows.filter((r) => matchesQuery(r, query) && (filter === "all" || r.kind === filter));
}

/** Each card cut to the rows that remain, a card left with none dropped. */
export function narrow(cards: NameCard[], filter: PositionsFilter, query: string): NameCard[] {
  return cards
    .map((c) => ({ ...c, rows: narrowRows(c.rows, filter, query) }))
    .filter((c) => c.rows.length > 0);
}

/** How many rows each chip would show with the search applied. */
export function countByFilter(
  cards: NameCard[],
  spreads: PositionRow[],
  query: string,
): Record<PositionsFilter, number> {
  const all = [...cards.flatMap((c) => c.rows), ...spreads];
  return Object.fromEntries(FILTERS.map((f) => [f, narrowRows(all, f, query).length])) as Record<
    PositionsFilter,
    number
  >;
}
