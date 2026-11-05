/** The kinds of trade the console groups everything by (DESIGN.md Strategy switcher). */
export type StrategyKind = "csp" | "cc" | "spread" | "value";
export type StrategyFilter = "all" | StrategyKind;

export const STRATEGY_FILTERS: StrategyFilter[] = ["all", "csp", "cc", "spread", "value"];

/** The filters the wheel's own pages (Trades) offer: the value book has no proposals or history there. */
export const WHEEL_FILTERS: StrategyFilter[] = STRATEGY_FILTERS.filter((f) => f !== "value");

export const STRATEGY_LABEL: Record<StrategyFilter, string> = {
  all: "All",
  csp: "CSPs",
  cc: "CCs",
  spread: "Credit spreads",
  value: "Value",
};

export const STRATEGY_EYEBROW: Record<StrategyKind, string> = {
  csp: "Cash-secured put",
  cc: "Covered call",
  spread: "Credit spread",
  value: "Value book",
};

/**
 * Backend strategy name (+ option right for rolls) to a kind. A roll is filed under the side
 * it rolls: a put roll is still the CSP book. Unknown strategies return null and show only
 * under All - never guessed into a kind.
 */
export function kindOf(
  strategy: string | null | undefined,
  right: string | null | undefined,
): StrategyKind | null {
  if (strategy === "cash_secured_put") return "csp";
  if (strategy === "covered_call") return "cc";
  if (strategy === "credit_spread") return "spread";
  if (strategy === "roll") {
    if (right === "P") return "csp";
    if (right === "C") return "cc";
  }
  return null;
}

export function parseStrategyFilter(
  raw: string | null | undefined,
  allowed: StrategyFilter[] = STRATEGY_FILTERS,
): StrategyFilter {
  return (allowed as string[]).includes(raw ?? "") ? (raw as StrategyFilter) : "all";
}

export function matchesFilter(kind: StrategyKind | null, filter: StrategyFilter): boolean {
  return filter === "all" || kind === filter;
}
