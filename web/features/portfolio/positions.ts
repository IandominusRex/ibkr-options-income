import type { OptionLeg, PositionGroupData } from "@/components/portfolio/types";
import { type PositionRow, buildPositionRows, matchesQuery } from "@/features/home/positions";
import type { SpreadPosition } from "@/features/home/types";
import { formatMoneyCell } from "@/lib/money";
import { STRATEGY_LABEL } from "@/lib/strategy";
import { weekdayDate } from "./format";

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

/** A name's price: the share position's own, or the last settled close (dated) for a name held only through options. */
export type NamePrice = { value: number; basis: "position" | "close"; date: string | null };

export type NameCard = {
  underlying: string;
  rows: PositionRow[];
  /** The figure line under each option row, by row key. */
  details: Record<string, DetailPart[]>;
  price: NamePrice | null;
  /** The API's group, for the figures the card reads beside its rows. */
  group: PositionGroupData;
};

function priceOf(g: PositionGroupData): NamePrice | null {
  if (g.underlying_price !== null && g.underlying_price !== undefined) {
    return { value: g.underlying_price, basis: g.underlying_price_basis ?? "position", date: g.underlying_price_date ?? null };
  }
  // An API that predates `underlying_price` still sends the share position's own price.
  const held = g.stock?.market_price;
  return held !== null && held !== undefined && g.underlying_price === undefined ? { value: held, basis: "position", date: null } : null;
}

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
      price: priceOf(g),
      group: g,
    }))
    .filter((c) => c.rows.length > 0)
    .sort((a, b) => a.underlying.localeCompare(b.underlying));
}

export type NameFigure = { label: string; value: string | null };

const PLURAL: Record<string, [string, string]> = {
  csp: ["cash-secured put", "cash-secured puts"],
  cc: ["covered call", "covered calls"],
  other: ["option", "options"],
};

/** "100 shares · avg $182.4 · 1 covered call": what the name is made of, from the rows the card shows. */
export function nameSummary(card: NameCard): string {
  const parts: string[] = [];
  const stock = card.rows.some((r) => r.kind === "shares") ? card.group.stock : null;
  if (stock) {
    const n = stock.shares;
    parts.push(`${n.toLocaleString("en-US", { maximumFractionDigits: 2 })} ${n === 1 ? "share" : "shares"}`);
    parts.push(`avg ${formatMoneyCell(stock.avg_cost)}`);
  }
  for (const kind of ["csp", "cc", "other"] as const) {
    const n = card.rows.filter((r) => r.kind === kind).length;
    if (n > 0) parts.push(`${n} ${PLURAL[kind][n === 1 ? 0 : 1]}`);
  }
  return parts.join(" · ");
}

/**
 * The figures a name card reads under its open P&L, from the rows it shows (so a type chip narrows
 * them with the rows): the shares' value and the cost basis they are measured against (the
 * premium-adjusted one when there is one, the same figure the P&L uses), the net delta in shares,
 * the nearest expiry and the cash secured by its short puts. A figure we do not have is null,
 * never 0, and a sum with a missing part is null, not the rest added up.
 */
export function nameFigures(card: NameCard): NameFigure[] {
  const stock = card.rows.some((r) => r.kind === "shares") ? card.group.stock : null;
  const keys = new Set(card.rows.map((r) => r.key));
  const opts = card.group.options.filter((o) => keys.has(`${card.underlying}:${o.symbol}`));
  const out: NameFigure[] = [];
  const money = (v: number | null | undefined) => (v === null || v === undefined ? null : formatMoneyCell(v));

  if (stock) {
    out.push({ label: "Value", value: money(stock.market_value) });
    const adjusted = stock.adjusted_cost_basis !== null && stock.adjusted_cost_basis !== undefined;
    out.push({
      label: adjusted ? "Adjusted cost" : "Cost basis",
      value: money((stock.adjusted_cost_basis ?? stock.avg_cost) * stock.shares),
    });
  }

  if (stock || opts.length > 0) {
    // A short option's delta counts against the shares: a short put is long the stock.
    const deltas = opts.map((o) => (o.delta === null || o.delta === undefined ? null : o.delta * o.contracts * 100 * (o.short ? -1 : 1)));
    const net = deltas.some((d) => d === null) ? null : (stock?.shares ?? 0) + deltas.reduce<number>((a, d) => a + (d ?? 0), 0);
    out.push({
      label: "Net delta",
      value: net === null ? null : `${net > 0 ? "+" : net < 0 ? "−" : ""}${Math.abs(Math.round(net)).toLocaleString("en-US")} sh`,
    });
  }

  const dated = opts.filter((o) => o.expiry).sort((a, b) => (a.expiry as string).localeCompare(b.expiry as string));
  if (dated.length > 0) {
    const next = dated[0];
    out.push({ label: "Next expiry", value: `${weekdayDate(next.expiry as string)}${next.dte === null ? "" : ` · ${next.dte}d`}` });
  }

  const puts = opts.filter((o) => o.short && o.right === "P");
  if (puts.length > 0) {
    out.push({
      label: "Cash secured",
      value: puts.some((o) => o.strike === null || o.strike === undefined)
        ? null
        : formatMoneyCell(puts.reduce((a, o) => a + (o.strike as number) * o.contracts * 100, 0)),
    });
  }
  return out;
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
