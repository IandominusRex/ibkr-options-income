"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ClaudeContext } from "./types";

/**
 * The one request behind everything the market-picture build shows (What Claude knows, Home's
 * Market card, a name's notes, Trades, News). One query key, so a page that mounts several of
 * them asks once; a failed request leaves each consumer to say so itself.
 */
export function useClaudeContext() {
  return useQuery({
    queryKey: ["claude-context"],
    queryFn: () => apiFetch<ClaudeContext>("/claude/context"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
