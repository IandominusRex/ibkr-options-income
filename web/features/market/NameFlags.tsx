"use client";

import { StatusWord } from "@/components/ui/StatusWord";
import { shortDay } from "@/features/claude-context/format";
import { useClaudeContext } from "@/features/claude-context/useClaudeContext";
import { todayInNewYork } from "@/features/trades/time";
import { nameFlags } from "./market";

/**
 * Status words for a position row from its name's notes: "Weak health" when Python's quality
 * screen says so, and the nearest dated event within ten days. Nothing while the notes load, when
 * they are missing, or when there is nothing to flag, so a quiet name stays quiet.
 */
export function NameFlags({ symbol }: { symbol: string }) {
  const { data } = useClaudeContext();
  const d = data?.dossiers?.find((x) => x.symbol === symbol.toUpperCase());
  const { weak, event } = nameFlags(d, todayInNewYork());
  if (!weak && !event) return null;
  return (
    <>
      {weak && (
        <span className="ml-1.5 align-[1px]">
          <StatusWord tone="flag">Weak health</StatusWord>
        </span>
      )}
      {event && (
        <span className="ml-1.5 align-[1px]">
          <StatusWord>{`Event ${shortDay(event)}`}</StatusWord>
        </span>
      )}
    </>
  );
}
