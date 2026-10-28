/** The account donut's arithmetic: what each ring says, as plain numbers a test can check. */

/** Cash as a percent of the account's net liquidation, or null when either is unknown or the account is not positive. */
export function cashPct(cash: number | null, netLiq: number | null): number | null {
  if (cash === null || netLiq === null || netLiq <= 0) return null;
  return (cash / netLiq) * 100;
}

/** How much of a ring is drawn for a percent: 0 to 1, so 140% fills it and a negative percent draws nothing. */
export function ringFraction(pct: number | null): number {
  if (pct === null || Number.isNaN(pct)) return 0;
  return Math.min(1, Math.max(0, pct / 100));
}

/** A percent as the legend writes it: one decimal, a real minus, "n/a" never "0.0%" for unknown. */
export function pctLabel(pct: number | null): string | null {
  if (pct === null || Number.isNaN(pct)) return null;
  return `${pct < 0 ? "−" : ""}${Math.abs(pct).toFixed(1)}%`;
}
