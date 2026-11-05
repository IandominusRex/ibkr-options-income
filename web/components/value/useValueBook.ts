"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ValueBook, ValueProposal } from "./types";

/**
 * `GET /value/book`, one query for every reader on Home (the Value card and the strategy
 * switcher's count): one request, one refetch clock.
 */
export function useValueBook() {
  return useQuery({
    queryKey: ["value", "book"],
    queryFn: () => apiFetch<ValueBook>("/value/book"),
    refetchInterval: 60_000,
  });
}

/**
 * How many of the book's proposals wait on a tap. Null when the book could not be read: an
 * unreadable book is not an empty one, so the switcher shows no count rather than a zero.
 */
export function waitingOnTap(book: ValueBook | undefined): number | null {
  if (!book || !book.available) return null;
  return (book.proposals ?? []).filter((p) => p.needs_tap && p.status === "pending").length;
}

/**
 * Whether to flag the value book as unavailable beside a P&L figure (web overhaul Part 4, ruling 7). The pay
 * routes answer `value_available: false` both when value.db cannot be read and when it was never written; a
 * book that is off and has never written anything has no sales to miss, so it is not flagged. A book read
 * that failed or is still loading keeps the flag: unknown is not none.
 */
export function useValueOut(valueAvailable: boolean | undefined): boolean {
  const { data } = useValueBook();
  if (valueAvailable !== false) return false;
  return !(data !== undefined && data.enabled === false && data.available === false);
}

/**
 * The book's proposals that wait on a tap, in the book's order (web overhaul Part 4, ruling 15). Null, not an
 * empty list, when the book could not be read: the same rule as `waitingOnTap`.
 */
export function waitingProposals(book: ValueBook | undefined): ValueProposal[] | null {
  if (!book || !book.available) return null;
  return (book.proposals ?? []).filter((p) => p.needs_tap && p.status === "pending");
}
