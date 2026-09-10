import { UNKNOWN, relativeAge } from "./format";

export type MoneyKind = "realized" | "unrealized" | "value" | "basis";

export interface MoneyProps {
  value: number | null | undefined;
  kind: MoneyKind;
  /** When false, the figure excludes commissions and says so. */
  complete?: boolean;
  /** Render a leading + on positives. Off for values, on for P&L. */
  signed?: boolean;
  asOf?: string | null;
}

const CENTS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * "$1,234.56", "-$1,234.56", "$0", or UNKNOWN. Never "$0.00" for a null.
 *
 * Deliberately not `formatMoney` (lib/format.ts): that formatter is compact notation
 * ($1.2K, $391.0B, no cents) for dashboard tiles. This one is full precision with comma
 * grouping and cents, for a money cell a reader reconciles against a statement.
 */
export function formatMoneyCell(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNKNOWN;
  if (value === 0) return "$0";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${CENTS.format(Math.abs(value))}`;
}

/** "12m ago" / "3h ago" / "2d ago". Null-safe: "not captured" rather than "just now". */
export function freshnessText(asOf: string | null | undefined): string {
  return relativeAge(asOf) || "not captured";
}

/** True when as_of is older than the threshold the API's `stale` flag uses. */
export function isStale(asOf: string | null | undefined, freshForMinutes: number): boolean {
  if (!asOf) return true;
  const then = new Date(asOf).getTime();
  if (Number.isNaN(then)) return true;
  const ageMinutes = (Date.now() - then) / 60000;
  return ageMinutes > freshForMinutes;
}
