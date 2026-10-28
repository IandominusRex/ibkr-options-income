import { formatStubValue } from "@/components/ui/Stub";
import { kindWord } from "@/features/market/market";
import type { SizingGroup } from "./types";

const SPLIT: Record<string, string> = {
  sent_smaller: "sent smaller",
  never_sent: "never sent",
  pushed_out: "pushed out",
};

/** "Scale-in ladder · never sent"; Claude's cuts are one line, whichever way they were recorded. */
export function groupTitle(g: Pick<SizingGroup, "kind" | "split">): string {
  if (g.split === "overrides") return "Claude's size cut";
  return `${kindWord(g.kind)} · ${SPLIT[g.split] ?? g.split.replace(/_/g, " ")}`;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "2 actions · 1 valued so far · 4 contracts held back". */
export function groupSub(g: SizingGroup): string {
  const actions = plural(g.count, "action", "actions");
  if (g.split === "pushed_out") return `${actions} · counted, not valued`;
  return [
    actions,
    `${g.resolved ?? 0} valued so far`,
    `${plural(g.contracts_withheld ?? 0, "contract", "contracts")} held back`,
  ].join(" · ");
}

/** The sentence under a line, when it has something to add; null otherwise. */
export function groupNote(g: SizingGroup): string | null {
  if (g.split === "overrides") return `${g.applied ?? 0} applied, ${g.unapplied ?? 0} recorded only.`;
  if (g.split === "pushed_out") {
    return "A covered call was still sold on the name that day, so the breakout rule only pushed it out.";
  }
  const exact = g.exact ?? 0;
  if (exact > 0) {
    return exact === 1
      ? "1 of the valued rows is valued at the realised P&L of the contract that did trade."
      : `${exact} of the valued rows are valued at the realised P&L of the contracts that did trade.`;
  }
  return null;
}

export type Marks = { expiry: number | null; rules: number | null };

/**
 * The two marks of a line, or null where there is none to give: nothing valued yet (never a
 * zero), a pushed-out line, or no entry IV on any valued row (no exit-rule mark).
 */
export function marks(g: SizingGroup): Marks {
  if (g.split === "pushed_out" || !g.resolved) return { expiry: null, rules: null };
  const rulesKnown = (g.rules_missing ?? 0) < g.resolved;
  return { expiry: g.pnl_expiry ?? null, rules: rulesKnown ? (g.pnl_rules ?? null) : null };
}

/** Why some valued rows have no exit-rule mark; null when none is missing. */
export function rulesNote(g: SizingGroup): string | null {
  const n = g.rules_missing ?? 0;
  if (n <= 0) return null;
  return n === 1
    ? "1 valued row has no entry IV, so its exit-rule mark is left out."
    : `${n} valued rows have no entry IV, so their exit-rule mark is left out.`;
}

export const signedMark = (v: number): string => formatStubValue(v, "signed-money");
