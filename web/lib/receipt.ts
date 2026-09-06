import type { CommandStatus } from "./commands";
import type { OrderSummary } from "@/components/options/types";

/**
 * The receipt's state machine (P2 spec §9.2). Three rules govern it, each with a
 * test in receipt.test.ts:
 *
 * 1. `pending` never renders as `applied` — a queued approval that reads as an
 *    executed one is the single most dangerous failure mode in the design.
 * 2. The UI never claims a trade happened until `OrderRow` says so — `submitted`
 *    requires an order in a working state, `filled` requires filled_qty > 0.
 *    Neither is inferred from the command alone.
 * 3. A stalled drain is stated, not hidden — `stalled` is a distinct state with
 *    distinct copy, not a slower spinner.
 *
 * An `expired` command is terminal: the TTL sweep moved it on. It renders as
 * `failed` with the `ttl_expired` reason from `result`.
 */
export type ReceiptState =
  | "queued" // command pending, drain has not applied it
  | "applied" // the approval was mutated
  | "submitted" // an order is working at the broker
  | "filled" // a fill exists
  | "failed" // the command failed (or expired), with a reason
  | "stalled"; // pending, and the drain is not healthy

// "Working at the broker" means the order has actually reached IBKR: submitted
// or partial. A `queued` OrderRow has NOT reached the broker yet — the receipt
// stays `applied` ("order queued for execution"), per spec §9.2's example copy.
const WORKING: OrderSummary["state"][] = ["submitted", "partial"];

export function receiptState(
  command: CommandStatus,
  order: OrderSummary | null,
  drainHealthy: boolean,
): ReceiptState {
  // Rule 1: pending is queued (healthy drain) or stalled (unhealthy drain),
  // regardless of anything else. The receipt must never read as executed
  // before the drain has actually applied the intent.
  if (command.status === "pending") {
    return drainHealthy ? "queued" : "stalled";
  }

  if (command.status === "failed") return "failed";
  if (command.status === "expired") return "failed";

  // status === "applied": the approval was mutated. What that MEANS depends on
  // the order, never on the command (rule 2).
  if (order === null) return "applied";
  if ((order.filled_qty ?? 0) > 0) return "filled";
  if (WORKING.includes(order.state)) return "submitted";
  // A cancelled/rejected order: the command applied, the order did not work.
  return "applied";
}

const COPY: Record<ReceiptState, string> = {
  queued: "accepted, waiting for the trading service",
  applied: "applied, order queued for execution",
  submitted: "working at IBKR",
  filled: "filled",
  failed: "did not apply",
  stalled: "the trading service is not draining commands",
};

const LABEL: Record<ReceiptState, string> = {
  queued: "Queued",
  applied: "Applied",
  submitted: "Submitted",
  filled: "Filled",
  failed: "Failed",
  stalled: "Queued",
};

export function receiptCopy(state: ReceiptState): string {
  return COPY[state];
}

export function receiptLabel(state: ReceiptState): string {
  return LABEL[state];
}

/** Humanise a result.reason code for the failed receipt. */
export function humaniseReason(reason: string | undefined): string {
  if (!reason) return "unknown reason";
  return reason.replace(/_/g, " ");
}