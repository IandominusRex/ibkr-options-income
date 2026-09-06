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
 */
export function CommandReceipt({
  command,
  order,
  drainHealthy,
}: {
  command: CommandStatus;
  order: OrderSummary | null;
  drainHealthy: boolean;
}) {
  // receiptState is a pure function (lib/receipt.ts) and the only source of state.
  const state = receiptState(command, order, drainHealthy);
  const label = receiptLabel(state);
  const copy = receiptCopy(state);
  const reason = failedReason(command);

  return (
    <div
      data-testid="command-receipt"
      data-state={state}
      className="mt-3 rounded-sm border border-border bg-background px-3 py-2 text-xs"
    >
      <p className="flex items-baseline gap-2">
        <span className={`font-medium ${stateTextClass(state)}`}>{label}</span>
        <span className="text-content">{copy}</span>
        <span className="ml-auto font-mono text-muted">intent {command.id}</span>
      </p>
      {state === "stalled" && (
        <p className="mt-1 text-loss" data-testid="stalled-words">
          the trading service is not draining commands
        </p>
      )}
      {reason && (
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
    | { reason?: string; detail?: { reasons?: string[]; reason?: string } }
    | null;
  if (!result || !("reason" in result) || result.reason === undefined) return null;
  const detailReasons =
    result.detail?.reasons ?? (result.detail?.reason ? [result.detail.reason] : []);
  return { primary: humaniseReason(result.reason), extra: detailReasons };
}