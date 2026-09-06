"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import {
  confirmCommand,
  submitCommand,
  useCommandStatus,
  type CommandStatus,
} from "@/lib/commands";
import type { ApprovalSummary, OrderSummary } from "./types";
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
 * - Controls are disabled while a command is in flight.
 * - A 403 renders a permission message, not a generic failure.
 * - In live mode the second confirmation is a distinct, clearly labelled step.
 * - Cancelling the live step leaves the intent queued and unconfirmed.
 */
export function DecideControls({
  approval,
  drainHealthy = true,
}: {
  approval: Pick<
    ApprovalSummary,
    "id" | "status" | "underlying" | "contracts" | "premium" | "right" | "strike" | "expiry"
  >;
  drainHealthy?: boolean;
}) {
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveStep, setLiveStep] = useState<CommandStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const qc = useQueryClient();

  // Poll every 2s while pending; stop once terminal (lib/commands.ts).
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  const orders = qc.getQueryData<OrderSummary[]>(["options", "orders"]);
  const order =
    current && current.status !== "pending"
      ? (orders ?? []).find((o) => o.approval_id === approval.id) ?? null
      : null;

  useEffect(() => {
    if (current && current.status !== "pending") {
      qc.invalidateQueries({ queryKey: ["options", "approvals"] });
      qc.invalidateQueries({ queryKey: ["options", "approval"] });
    }
  }, [current, qc]);

  async function onConfirm() {
    const kind = confirming;
    setConfirming(null);
    if (kind === null) return;
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitCommand(kind, { approval_id: approval.id });
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

  const inFlight = submitting || (current != null && current.status === "pending");
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