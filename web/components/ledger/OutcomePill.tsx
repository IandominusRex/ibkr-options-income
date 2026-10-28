import { StatusWord } from "@/components/ui/StatusWord";
import type { LedgerOutcome } from "./types";

// The word is the state; no colour carries it (web/DESIGN.md: states are words, never colour alone).
export function OutcomePill({ outcome, overridden = false }: { outcome: LedgerOutcome; overridden?: boolean }) {
  return (
    <StatusWord>
      {outcome}
      {overridden && (
        <span title="Outcome set by you" aria-label="overridden">
          *
        </span>
      )}
    </StatusWord>
  );
}
