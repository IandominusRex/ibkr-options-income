import { freshnessText, isStale } from "@/lib/money";

export interface FreshnessLabelProps {
  asOf: string | null | undefined;
  freshForMinutes: number;
}

/**
 * States a reading's age in words - never a coloured dot. A null `asOf` renders
 * "not captured" (distinct from "just now"); a reading older than `freshForMinutes`
 * says "stale" in words, matching the tag the stock page already uses for a delayed
 * quote (`app/stock/[symbol]/page.tsx`).
 */
export function FreshnessLabel({ asOf, freshForMinutes }: FreshnessLabelProps) {
  const text = freshnessText(asOf);
  const stale = asOf != null && isStale(asOf, freshForMinutes);

  return (
    <span className={`text-xs ${stale ? "text-unknown" : "text-muted"}`}>
      {text}
      {stale ? " · stale" : ""}
    </span>
  );
}
