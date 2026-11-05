"use client";

import { StatusWord } from "@/components/ui/StatusWord";
import { whenET } from "@/features/trades/time";
import { useValueBook } from "./useValueBook";

/**
 * The value process's drain, in words, under a value tap's receipt (web overhaul Part 4, ruling 5). The
 * protected CommandReceipt names "the trading service" when stalled, the wrong process for a value tap, so
 * the receipt is always given a healthy drain and this line says the true thing. Nothing while the command
 * is not pending, the drain is healthy, or the book has not been read (unknown is not stalled).
 */
export function ValueDrainNote({ pending }: { pending: boolean }) {
  const { data } = useValueBook();
  if (!pending || !data || data.drain_healthy) return null;
  const seen = data.drain_last_seen ?? null;
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem]" data-testid="value-drain-note">
      <StatusWord tone="flag">Not checking</StatusWord>
      <span>
        {seen
          ? `The value process last checked for taps ${whenET(seen)}. This tap waits until it checks again.`
          : "The value process has not checked for taps yet. This tap waits until it runs."}
      </span>
    </p>
  );
}
