import type { ApprovalSummary } from "@/components/options/types";
import { proposalTitle } from "@/features/home/ProposalCard";
import { decisionWords } from "@/features/home/proposal";
import { STRATEGY_EYEBROW, type StrategyFilter, kindOf, matchesFilter } from "@/lib/strategy";
import { newYorkDay, timeET } from "./time";

/**
 * Order states that are still in flight. Filled, partial, cancelled and rejected orders are history:
 * a partial order is one the executor already cancelled the rest of at its fill timeout, so the
 * broker holds nothing for it (2026-10-27: six stale partials from Sep 30 on read as "in flight").
 */
export const IN_FLIGHT_STATES = new Set(["queued", "submitted"]);

/** "$190 cash-secured put". An order carries the strategy name, not the option right. */
export function orderContract(o: { strategy: string; strike: number }): string {
  const k = kindOf(o.strategy, null);
  const kind = k ? STRATEGY_EYEBROW[k].toLowerCase() : o.strategy.replace(/_/g, " ");
  return `$${o.strike} ${kind}`;
}

export type NotTradedRow = {
  id: number;
  title: string;
  /** The outcome as a status word. */
  word: string;
  /** Who decided, from the record only ("Approved by the system", "Approved", "Expired unanswered"). */
  decision: string;
  raised: string;
  /** The proposal's premium (a roll's net) in dollars; null when unknown, never 0. */
  value: number | null;
  valueLabel: string;
};

function outcome(a: ApprovalSummary): string | null {
  if (a.status === "expired") return "Expired";
  if (a.status === "rejected") return "Rejected";
  if (a.status === "approved" && a.order_state === "cancelled") return "Order cancelled";
  if (a.status === "approved" && a.order_state === "rejected") return "Order rejected";
  return null; // pending, in flight, filled (a Traded card), or approved with no order of its own
}

/** Proposals raised on the New York `day` that ended without a fill, newest first. */
export function notTradedRows(approvals: ApprovalSummary[], day: string, strategy: StrategyFilter): NotTradedRow[] {
  const out: { at: number; row: NotTradedRow }[] = [];
  for (const a of approvals) {
    if (newYorkDay(a.created_at) !== day || !matchesFilter(kindOf(a.strategy, a.right), strategy)) continue;
    const word = outcome(a);
    if (word === null) continue;
    const isRoll = a.source === "roll" || a.strategy === "roll";
    out.push({
      at: Date.parse(a.created_at) || 0,
      row: {
        id: a.id,
        title: proposalTitle(a),
        word,
        decision: decisionWords(a.status, a.decided_by ?? null) ?? word,
        raised: `raised ${timeET(a.created_at)}`,
        value: a.premium === null ? null : a.premium * 100 * a.contracts,
        valueLabel: isRoll ? "net, as priced" : "premium",
      },
    });
  }
  return out.sort((x, y) => y.at - x.at).map((o) => o.row);
}
