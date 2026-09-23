"use client";

import type { CommandStatus } from "@/lib/commands";
import {
  humaniseReason,
  receiptCopy,
  receiptLabel,
  receiptState,
  type ReceiptState,
} from "@/lib/receipt";
import type { OrderSummary } from "./types";

/**
 * The command receipt — P2's signature component (spec §9.2).
 *
 * Answers one question: *did this actually happen?* The state comes from real
 * backend state via `receiptState` (lib/receipt.ts); this component only
 * renders it. Rules enforced here:
 *
 * - The state label and the `data-state` attribute differ per state, and states
 *   are never distinguished by colour alone (label text changes too).
 * - `stalled` renders "the trading service is not draining commands" in words —
 *   never a spinner (`role="progressbar"` must not appear).
 * - Every receipt shows its intent id, so an operator can ask about a specific
 *   command.
 * - `failed` renders the humanised `result.reason` plus any `result.detail`
 *   reason codes.
 * - The state transition animation is disabled under prefers-reduced-motion
 *   (the global rule in globals.css covers the CSS side; the animation itself
 *   is opt-in via the `animate-state` class, applied only when motion is OK).
 *
 * `plainReasons` (M3 Task 3.5) names `result.reason` codes that are a legitimate
 * answer, not an error - `broker_unavailable` on `RefreshControl` is the first
 * caller. A code listed here suppresses the red `text-loss` failed-state styling
 * and the "Failed" label; the receipt instead renders `data-state="answered"` in
 * the same plain/neutral style `ShortsRow`'s own forked `no_qualifying_roll`
 * rendering already established (border-border, bg-background, no text-loss).
 * Defaults to an empty array, so every existing call site (none of which passes
 * this prop) stays byte-identical. `ShortsRow` itself still forks its own markup
 * for `no_qualifying_roll` rather than using this prop - migrating that fork is
 * out of scope here.
 */
export function CommandReceipt({
  command,
  order,
  drainHealthy,
  plainReasons = [],
}: {
  command: CommandStatus;
  order: OrderSummary | null;
  drainHealthy: boolean;
  plainReasons?: string[];
}) {
  // receiptState is a pure function (lib/receipt.ts) and the only source of state.
  const state = receiptState(command, order, drainHealthy);
  const label = receiptLabel(state);
  const copy = receiptCopy(state);
  const reason = failedReason(command);
  const rawReason = failedReasonCode(command);
  const isPlain = state === "failed" && rawReason !== undefined && plainReasons.includes(rawReason);

  return (
    <div
      data-testid="command-receipt"
      data-state={isPlain ? "answered" : state}
      className="mt-3 rounded-sm border border-border bg-background px-3 py-2 text-xs"
    >
      <p className="flex items-baseline gap-2">
        <span className={`font-medium ${isPlain ? "text-content" : stateTextClass(state)}`}>
          {isPlain ? "Answered" : label}
        </span>
        <span className="text-content">{isPlain ? plainCopy(rawReason as string) : copy}</span>
        <span className="ml-auto font-mono text-muted">intent {command.id}</span>
      </p>
      {!isPlain && state === "stalled" && (
        <p className="mt-1 text-loss" data-testid="stalled-words">
          the trading service is not draining commands
        </p>
      )}
      {!isPlain && reason && (
        <p className="mt-1 text-loss">
          {reason.primary}
          {reason.extra.length > 0 && (
            <span className="text-muted"> ({reason.extra.map(humaniseReason).join(", ")})</span>
          )}
        </p>
      )}
    </div>
  );
}

function stateTextClass(state: ReceiptState): string {
  switch (state) {
    case "filled":
    case "applied":
    case "submitted":
      return "text-gain";
    case "failed":
      return "text-loss";
    case "stalled":
      return "text-loss";
    case "queued":
      return "text-muted";
  }
}

function failedReason(
  command: CommandStatus,
): { primary: string; extra: string[] } | null {
  const result = command.result as
    | {
        reason?: string;
        detail?: { reasons?: string[]; reason?: string; blockers?: string[] };
      }
    | null;
  if (!result || !("reason" in result) || result.reason === undefined) return null;
  // `detail.reasons` (promote's gate_rejected) and `detail.blockers`
  // (set_autonomy's promotion_refused, command_drain.py::_set_autonomy) are
  // two different key names for the same shape from two different command
  // handlers — without checking both, a refused promotion rendered
  // "Promotion refused" with every actual blocker silently dropped, telling
  // the operator nothing about what to fix.
  const detailReasons =
    result.detail?.reasons ??
    result.detail?.blockers ??
    (result.detail?.reason ? [result.detail.reason] : []);
  // Blockers are already full sentences, not snake_case codes — humaniseReason
  // is a no-op passthrough for text with no underscores, so it's safe to reuse
  // for both without a second mapping.
  return { primary: humaniseReason(result.reason), extra: detailReasons };
}

/** The raw (un-humanised) `result.reason` code, for matching against `plainReasons`. */
function failedReasonCode(command: CommandStatus): string | undefined {
  const result = command.result as { reason?: string } | null;
  return result?.reason;
}

// Friendlier copy for known plain reasons - a reason without an entry here
// still renders plainly (no red chrome, "Answered" label), just with the
// generic humanised reason text as its sentence.
const PLAIN_REASON_COPY: Record<string, string> = {
  broker_unavailable:
    "The broker is not connected right now. Nothing failed - try again once the connection is back.",
};

function plainCopy(reasonCode: string): string {
  return PLAIN_REASON_COPY[reasonCode] ?? `${humaniseReason(reasonCode)}.`;
}