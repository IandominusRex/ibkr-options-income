"use client";

import { relativeAge } from "@/lib/format";

/**
 * The "not draining" line that sits beside the halt and autonomy controls wherever they
 * render: in the shell's bot sheet and on Trades (`components/shell/BotSheet.tsx`). Shared so the
 * two surfaces cannot drift apart. The caller renders it only when `drain_healthy` is false.
 */
export function DrainWarning({ lastSeen }: { lastSeen: string | null }) {
  return (
    <p
      className="rounded-xl bg-flag px-3 py-2.5 text-[0.8125rem] text-on-flag"
      data-testid="drain-dead-warning"
    >
      the trading service is not draining commands
      {lastSeen ? ` (last seen ${relativeAge(lastSeen)})` : " (it has never run)"}
      . A click below queues an intent; it will not be applied until the drain
      is back.
    </p>
  );
}
