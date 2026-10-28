"use client";

import { useState } from "react";
import type { PnlLegData } from "@/components/pnl/types";

/**
 * The one filter state the totals, the equity curve and the legs list share (the P&L page's
 * rule: a second composition of the query string would let a total disagree with the rows under
 * it). `book` lives inside `filters`, so the book choice the summary offers on a mixed book and the
 * Legs form's own Book field cannot disagree. `viewLeg` sets the symbol from a leg the totals name,
 * and bumps `formKey` so the form remounts with it as its seed rather than syncing in an effect.
 */
export function useLegFilters() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [formKey, setFormKey] = useState(0);
  const book = filters.book || "all";

  const setBook = (next: string) => setFilters((prev) => ({ ...prev, book: next }));
  const viewLeg = (leg: PnlLegData) => {
    setFilters((prev) => ({ ...prev, symbol: leg.underlying }));
    setFormKey((k) => k + 1);
  };

  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "" && v != null)),
  );
  if (!qs.has("book")) qs.set("book", "all");

  return { filters, setFilters, book, setBook, formKey, viewLeg, qsString: qs.toString() };
}
