"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CommandReceipt } from "@/components/options/CommandReceipt";
import { ConfirmAction } from "@/components/options/ConfirmAction";
import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api";
import {
  confirmCommand,
  loadPersistedCommand,
  savePersistedCommand,
  submitCommand,
  useCommandStatus,
  type CommandStatus,
} from "@/lib/commands";
import { approveSentence, failureSentence, rejectSentence } from "./format";
import { ValueDrainNote } from "./ValueDrainNote";
import type { ValueProposalLike } from "./types";

/** The decision, in words, for a proposal that is no longer waiting on a tap. */
const DECISION: Record<string, string> = {
  approved: "approved",
  funding: "approved, waiting for cash",
  sent: "approved, order sent",
};

/**
 * Approve or reject one value-book proposal (plan ruling 31). It mirrors DecideControls' shape and
 * leaves that component alone: the confirmation comes first, one POST /commands follows, a receipt
 * follows the command, both buttons stay disabled while it is in flight, and the in-flight command
 * survives a reload under the key `value:<proposal id>`.
 *
 * The tap carries the fingerprint from GET /value/book, so a button on an old card cannot approve a
 * different trade. A tap changes only the proposal's row: nothing is sent to the broker until the
 * value process's next check has gated the order again on a fresh quote.
 */
export function ValueDecide({
  proposal,
  releaseMaxCloses,
  drainHealthy = true,
}: {
  proposal: ValueProposalLike;
  /** `release.max_closes_per_request` from GET /value/book: the K in the approval sentence. */
  releaseMaxCloses: number;
  /**
   * The receipt's drain flag. Defaults to healthy and should stay there: the protected receipt names "the
   * trading service" when stalled, the wrong process for a value tap, so the value process's own drain is
   * said by `ValueDrainNote` (web overhaul Part 4, ruling 5).
   */
  drainHealthy?: boolean;
}) {
  const subject = `value:${proposal.id}`;
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [liveStep, setLiveStep] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();

  // A reload (or the sheet opened again) while a command was pending: pick it back up.
  useEffect(() => {
    const persisted = loadPersistedCommand(subject);
    if (!persisted) return;
    if (persisted.needs_confirmation) setLiveStep(persisted);
    else setCommand(persisted);
    // Mount-only, as in DecideControls: the subject never changes under one instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  useEffect(() => {
    if (liveStep) savePersistedCommand(subject, liveStep);
    else if (current && current.status === "pending") savePersistedCommand(subject, current);
    else savePersistedCommand(subject, null);
  }, [subject, liveStep, current]);

  useEffect(() => {
    if (current && current.status !== "pending") {
      // The book's proposals (and so the fingerprint a retry must carry) are asked for again.
      qc.invalidateQueries({ queryKey: ["value", "book"] });
    }
  }, [current, qc]);

  async function onConfirm() {
    const which = confirming;
    setConfirming(null);
    if (which === null) return;
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitCommand(which === "approve" ? "value_approve" : "value_reject", {
        proposal_id: proposal.id,
        fingerprint: proposal.fingerprint,
      });
      if (resp.needs_confirmation && resp.confirm_token) setLiveStep(resp);
      else setCommand(resp);
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

  const inFlight = submitting || liveStep != null || (current != null && current.status === "pending");
  const decided = proposal.status !== "pending";
  const failure =
    current && (current.status === "failed" || current.status === "expired")
      ? failureSentence((current.result as { reason?: string } | null)?.reason)
      : null;
  const approvedNow = current?.status === "applied" && current.kind === "value_approve";

  return (
    <>
      {decided ? (
        <p className="mt-3 text-sm text-muted">Decision: {DECISION[proposal.status] ?? proposal.status}</p>
      ) : (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button variant="secondary" disabled={inFlight} onClick={() => setConfirming("approve")}>
            Approve
          </Button>
          <Button variant="quiet" disabled={inFlight} onClick={() => setConfirming("reject")}>
            Reject
          </Button>
        </div>
      )}

      {error && (
        <p className="mt-3 text-xs text-loss" role="alert">
          {error}
        </p>
      )}

      {current && <CommandReceipt command={current} order={null} drainHealthy={drainHealthy} />}
      <ValueDrainNote pending={current?.status === "pending"} />
      {failure && <p className="mt-2 text-sm">{failure}</p>}
      {approvedNow && (
        <p className="mt-2 text-sm">
          Approved. Nothing has been sent yet: the value process places the order at its next check, after the gate
          reads a fresh quote.
        </p>
      )}

      {liveStep && (
        <ConfirmAction
          title={`Confirm LIVE ${liveStep.kind}`}
          summary={
            <span>
              This is the second, mandatory confirmation for live trading. The first confirmation queued the intent;
              releasing it now lets the value process apply it.
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
          title={confirming === "approve" ? "Approve this proposal" : "Reject this proposal"}
          summary={
            <span>
              {confirming === "approve" ? approveSentence(proposal, releaseMaxCloses) : rejectSentence(proposal)}
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
