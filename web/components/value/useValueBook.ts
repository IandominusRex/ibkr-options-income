"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ValueBook } from "./types";

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
