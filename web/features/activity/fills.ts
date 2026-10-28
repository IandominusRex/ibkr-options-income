import { shortDay } from "@/features/claude-context/format";
import { usd } from "@/features/portfolio/format";
import type { LedgerExecution, SpreadOrder } from "./types";

/** The look-back windows the lists share (days). */
export const WINDOWS = [7, 30, 90, 365] as const;
export const DEFAULT_WINDOW = 30;

/** A window chip: "7 days", "A year". */
export const windowLabel = (days: number): string => (days === 365 ? "A year" : `${days} days`);

/** A window in a sentence: "the last 30 days", "the last year". */
export const lastWindow = (days: number): string => (days === 365 ? "the last year" : `the last ${days} days`);

/** "Sold 1 NVDA $165 put · Nov 20", from the sign of the quantity; shares are "Bought 100 AMZN shares". */
export function executionTitle(
  e: Pick<LedgerExecution, "quantity" | "underlying" | "sec_type" | "right" | "strike" | "expiry">,
): string {
  const side = e.quantity < 0 ? "Sold" : "Bought";
  const n = Math.abs(e.quantity);
  if (e.sec_type !== "OPT") return `${side} ${n} ${e.underlying} shares`;
  const strike = typeof e.strike === "number" ? usd(e.strike) : "strike n/a";
  const base = `${side} ${n} ${e.underlying} ${strike} ${e.right === "C" ? "call" : "put"}`;
  return e.expiry ? `${base} · ${shortDay(e.expiry)}` : base;
}

const BOOK: Record<string, string> = { system: "System", spreads: "Spreads", manual: "Manual" };
const SOURCE: Record<string, string> = { live: "live feed", flex: "Flex query", csv: "statement import" };

export const bookWord = (book: string): string => BOOK[book] ?? book;
export const sourceWord = (source: string): string => SOURCE[source] ?? source;

/** "SPY 763/758 put spread", or a sentence saying the strikes are not known. */
export function spreadOrderTitle(
  o: Pick<SpreadOrder, "short_strike" | "long_strike" | "side">,
  underlying: string,
): string {
  if (o.short_strike == null || o.long_strike == null || !o.side) return `${underlying} credit spread, strikes n/a`;
  return `${underlying} ${o.short_strike}/${o.long_strike} ${o.side} spread`;
}
