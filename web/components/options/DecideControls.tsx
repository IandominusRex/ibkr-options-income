"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import {
  confirmCommand,
  loadPersistedCommand,
  savePersistedCommand,
  submitCommand,
  useCommandStatus,
  type CommandStatus,
} from "@/lib/commands";
import type { ApprovalSummary, OrderListResponse } from "./types";
import { ConfirmAction } from "./ConfirmAction";
import { CommandReceipt } from "./CommandReceipt";

/**
 * The decide flow shared by the approval card and the approval detail page
 * (M3 Tasks 3.4/3.5). One hook, one JSX block, both surfaces — a divergence
 * between them would be a divergence in how an approval is decided.
 *
 * Behaviours (each tested in ApprovalCard.test.tsx):
 * - Approve/Reject open ConfirmAction before any request is made.
 * - On confirm, POST /commands fires once; the returned id drives the receipt.
 * - Controls are disabled while a command is in flight, including while the
 *   live second-confirmation dialog is open (no command id to poll yet).
 * - A 403 renders a permission message, not a generic failure.
 * - In live mode the second confirmation is a distinct, clearly labelled step,
 *   and survives both a tab-switch remount and a full page reload.
 * - Cancelling the live step leaves the intent queued and unconfirmed.
 */
export function DecideControls({
  approval,
  drainHealthy = true,
  initialCommand = null,
  onApprovalSubmitted,
  onApprovalSettled,
}: {
  approval: Pick<
    ApprovalSummary,
    "id" | "status" | "underlying" | "contracts" | "premium" | "right" | "strike" | "expiry"
  >;
  drainHealthy?: boolean;
  /**
   * A command already known to be in flight for this approval when this
   * component first mounts (M3b: the Approvals/Submitted split unmounts and
   * remounts the card when it moves between tabs — without this, the new
   * mount would start from a blank slate and lose the in-flight receipt).
   * Only read on the initial render, like any React initial-state value. A
   * `needs_confirmation` command restores the live second-confirmation step,
   * not the plain receipt — otherwise a card that moved to "Submitted" the
   * instant Approve was confirmed would strand that dialog on the old mount.
   * When omitted, the component falls back to whatever `lib/commands.ts`'s
   * localStorage persistence has for this approval id (a page reload, or the
   * detail page, which has no `submitted` map of its own to pass this from).
   */
  initialCommand?: CommandStatus | null;
  /** Fired the moment Approve is confirmed (before the network call even
   * resolves) so a caller can move the card to a "Submitted" view. */
  onApprovalSubmitted?: (id: number, command: CommandStatus) => void;
  /** Fired if the command ends up failed/expired — the approval never left
   * "pending" server-side, so it belongs back in the Approvals view. */
  onApprovalSettled?: (id: number) => void;
}) {
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);
  const [command, setCommand] = useState<CommandStatus | null>(
    initialCommand && !initialCommand.needs_confirmation ? initialCommand : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [liveStep, setLiveStep] = useState<CommandStatus | null>(
    initialCommand?.needs_confirmation ? initialCommand : null,
  );
  const [submitting, setSubmitting] = useState(false);

  // No `initialCommand` was passed (a fresh mount, not a tab-switch remount) —
  // fall back to localStorage, e.g. a page reload while a command was pending,
  // or the detail page, which never receives `initialCommand` from a parent.
  useEffect(() => {
    if (initialCommand) return;
    const persisted = loadPersistedCommand(approval.id);
    if (!persisted) return;
    if (persisted.needs_confirmation) setLiveStep(persisted);
    else setCommand(persisted);
    // Deliberately mount-only: `approval.id` does not change under a given
    // DecideControls instance, and re-running this on every render would
    // overwrite a command the user is actively progressing through.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const qc = useQueryClient();

  // Poll every 2s while pending; stop once terminal (lib/commands.ts).
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  // The orders list is cached under the same key by <OrdersTable/> as an
  // OrderListResponse ({ as_of, orders: [...] }) — NOT a bare OrderSummary[].
  // Reading it as the wrong shape silently made `order` always undefined, so a
  // receipt could never advance to `submitted`/`filled` from the cache. Also
  // invalidate it when a command goes terminal so the next poll sees the new
  // order the drain just created.
  const cached = qc.getQueryData<OrderListResponse>(["options", "orders"]);
  const orders = cached?.orders ?? null;
  const order =
    current && current.status !== "pending"
      ? (orders ?? []).find((o) => o.approval_id === approval.id) ?? null
      : null;

  // Mirror the in-flight command to localStorage so it survives a reload and is
  // visible from the detail page too — keyed off `current` (the polled value),
  // not the raw `command` state, so this clears the moment the drain actually
  // applies/fails/expires it, not just when this component happens to call
  // setCommand again. `liveStep` takes priority: while the live dialog is open
  // there is no polled `current` yet (no command id exists server-side until
  // the intent is released), so it's the only in-flight state to persist.
  useEffect(() => {
    if (liveStep) {
      savePersistedCommand(approval.id, liveStep);
    } else if (current && current.status === "pending") {
      savePersistedCommand(approval.id, current);
    } else {
      savePersistedCommand(approval.id, null);
    }
  }, [approval.id, liveStep, current]);

  useEffect(() => {
    if (current && current.status !== "pending") {
      qc.invalidateQueries({ queryKey: ["options", "approvals"] });
      qc.invalidateQueries({ queryKey: ["options", "approval"] });
      qc.invalidateQueries({ queryKey: ["options", "orders"] });
      // A failed/expired approve never left "pending" server-side, so it
      // belongs back in the Approvals view, not stranded in "Submitted".
      // `applied` needs no such reversal: the approval has already dropped
      // out of the pending query, so it's gone from both views regardless.
      if (current.kind === "approve" && (current.status === "failed" || current.status === "expired")) {
        onApprovalSettled?.(approval.id);
      }
    }
  }, [current, qc, approval.id, onApprovalSettled]);

  async function onConfirm() {
    const kind = confirming;
    setConfirming(null);
    if (kind === null) return;
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitCommand(kind, { approval_id: approval.id });
      if (kind === "approve") onApprovalSubmitted?.(approval.id, resp);
      if (resp.needs_confirmation && resp.confirm_token) {
        setLiveStep(resp);
      } else {
        setCommand(resp);
      }
    } catch (e) {
      setError(describeError(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function onLiveConfirm() {
    const cmd = liveStep;
    setLiveStep(null);
    if (cmd === null) return;
    setSubmitting(true);
    try {
      await confirmCommand(cmd.id, cmd.confirm_token ?? "");
      setCommand({ ...cmd, needs_confirmation: false, confirm_token: null });
    } catch (e) {
      setError(describeError(e));
    } finally {
      setSubmitting(false);
    }
  }

  // liveStep counts as in flight too: there is no command id to poll yet (the
  // intent only reaches `/commands/{id}` once the confirm token is released),
  // so `current` alone would miss this window and leave Approve/Reject
  // clickable while the live confirmation dialog is already open.
  const inFlight =
    submitting || liveStep != null || (current != null && current.status === "pending");
  const decided = approval.status !== "pending";

  return (
    <>
      {decided ? (
        <p className="mt-3 text-xs text-muted" data-testid="approval-decision">
          Decision: {approval.status}
        </p>
      ) : (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            disabled={inFlight}
            onClick={() => setConfirming("approve")}
            className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={inFlight}
            onClick={() => setConfirming("reject")}
            className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
          >
            Reject
          </button>
        </div>
      )}

      {error && (
        <p className="mt-3 text-xs text-loss" data-testid="command-error" role="alert">
          {error}
        </p>
      )}

      {current && (
        <CommandReceipt command={current} order={order} drainHealthy={drainHealthy} />
      )}

      {liveStep && (
        <ConfirmAction
          title={`Confirm LIVE ${liveStep.kind}`}
          summary={
            <span>
              This is the second, mandatory confirmation for live trading. The
              first confirmation queued the intent; releasing it now lets the
              trading service apply it. The execution-time [CONFIRM LIVE] Telegram
              step still fires afterwards.
            </span>
          }
          confirmLabel={`Release ${liveStep.kind} intent`}
          onConfirm={onLiveConfirm}
          onCancel={() => {
            setCommand(liveStep);
            setLiveStep(null);
          }}
        />
      )}

      {confirming && (
        <ConfirmAction
          title={confirming === "approve" ? "Approve this contract" : "Reject this contract"}
          summary={
            <span>
              {confirming === "approve" ? "Approve" : "Reject"} exactly{" "}
              {approval.contracts} contract{approval.contracts === 1 ? "" : "s"} of{" "}
              {approval.underlying} {formatContract(approval)}
              {approval.premium != null
                ? ` at $${approval.premium.toFixed(2)} per share ($${(approval.premium * approval.contracts * 100).toFixed(0)} total)`
                : ""}
              . {confirming === "approve"
                ? "An order will be queued for execution."
                : "The candidate will be recorded as rejected."}
            </span>
          }
          confirmLabel={confirming === "approve" ? "Approve" : "Reject"}
          onConfirm={onConfirm}
          onCancel={() => setConfirming(null)}
        />
      )}
    </>
  );
}

function describeError(e: unknown): string {
  if (e instanceof ApiError && e.status === 403) {
    return "You do not have permission to do this. Command not created.";
  }
  return "The command could not be created. Nothing was sent.";
}

function formatContract(
  a: Pick<ApprovalSummary, "right" | "strike" | "expiry">,
): string {
  const right = a.right === "C" ? "C" : "P";
  const strike = a.strike.toFixed(2);
  const expiry = a.expiry ? a.expiry.slice(2, 10).replace(/-/g, "") : "??";
  return `${strike} ${right} ${expiry}`;
}