"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import {
  confirmCommand,
  submitCommand,
  useCommandStatus,
  type CommandStatus,
} from "@/lib/commands";
import type { AssessedContract } from "./types";
import { StageBadge } from "./StageBadge";
import { ConfirmAction } from "./ConfirmAction";
import { CommandReceipt } from "./CommandReceipt";

/**
 * One assessed-contract row, extracted from `AssessedBrowser`'s `Group` so the
 * promote control (P2 M4 Task 4.3) has somewhere to live without turning
 * `AssessedBrowser` into a second copy of the decide flow.
 *
 * The promote flow mirrors `DecideControls` exactly (M3): a `confirming` state
 * gates a `<ConfirmAction/>` before any request, `submitCommand("promote", ...)`
 * fires once on confirm, a live-mode response routes through a second,
 * distinctly labelled LIVE confirmation, and `useCommandStatus` polls the
 * result until terminal. `<CommandReceipt/>` renders the outcome unmodified;
 * `order` is always `null` here — a promote never has the working-order
 * lifecycle approve/reject do, it only ever produces a new approval.
 *
 * `canPromote` is the single gate for both branches of the row: the raw
 * `promotable` flag from the API is trusted, but `strike`/`expiry` are
 * nullable on the type even though a promotable row always carries both in
 * practice. If that ever isn't true, the row falls through to the
 * non-promotable rendering (the note, if any) rather than crash or send
 * `null` to `POST /commands`.
 */
export function AssessedRow({
  contract,
  drainHealthy = true,
}: {
  contract: AssessedContract;
  drainHealthy?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveStep, setLiveStep] = useState<CommandStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const qc = useQueryClient();

  // Poll every 2s while pending; stop once terminal (lib/commands.ts).
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  useEffect(() => {
    if (current && current.status !== "pending") {
      qc.invalidateQueries({ queryKey: ["options", "assessed"] });
      qc.invalidateQueries({ queryKey: ["options", "approvals"] });
    }
  }, [current, qc]);

  const canPromote =
    contract.promotable && contract.strike != null && contract.expiry != null;
  const inFlight = submitting || (current != null && current.status === "pending");

  async function onConfirm() {
    setConfirming(false);
    if (!canPromote) return;
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitCommand("promote", {
        candidate_id: contract.candidate_id,
        symbol: contract.symbol,
        strategy: contract.strategy,
        strike: contract.strike,
        expiry: contract.expiry,
      });
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

  const approvalId =
    current?.status === "applied"
      ? ((current.result as { approval_id?: number | null } | null)?.approval_id ?? null)
      : null;

  return (
    <li className="px-4 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <StageBadge stage={contract.stage} />
          <span className="tabular font-mono text-xs text-content">
            {contract.strike != null ? contract.strike.toFixed(2) : "?"} {contract.strategy}
          </span>
        </div>
        <span className="tabular text-xs text-muted">
          {contract.blended_score != null ? contract.blended_score.toFixed(1) : "n/a"}
        </span>
      </div>
      {contract.reasons_text.length > 0 && (
        <p className="mt-1 text-xs text-muted">{contract.reasons_text.join(" - ")}</p>
      )}
      {!canPromote && contract.promote_note && (
        <p className="mt-1 text-xs text-muted">{contract.promote_note}</p>
      )}

      {canPromote && (
        <div className="mt-2">
          <button
            type="button"
            disabled={inFlight}
            onClick={() => setConfirming(true)}
            className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
          >
            Promote
          </button>
        </div>
      )}

      {error && (
        <p className="mt-2 text-xs text-loss" data-testid="command-error" role="alert">
          {error}
        </p>
      )}

      {current && (
        <CommandReceipt command={current} order={null} drainHealthy={drainHealthy} />
      )}

      {approvalId != null && (
        <p className="mt-1 text-xs">
          <Link
            href={`/options/${approvalId}`}
            className="text-content underline hover:text-focus focus-visible:ring-focus"
          >
            View approval
          </Link>
        </p>
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

      {confirming && canPromote && (
        <ConfirmAction
          title="Promote this contract"
          summary={
            <span>
              This will price {contract.symbol}{" "}
              {contract.strike != null ? contract.strike.toFixed(2) : "?"}{" "}
              {contract.strategy.replace(/_/g, " ")} again and check it against the Rules
              Engine again; an approval appears only if it still passes.
              {contract.stage === "score_floor" && contract.blended_score != null && (
                <>
                  {" "}
                  This contract scored {contract.blended_score.toFixed(1)}.{" "}
                  {contract.promote_note}
                </>
              )}
            </span>
          }
          confirmLabel="Promote"
          onConfirm={onConfirm}
          onCancel={() => setConfirming(false)}
        />
      )}
    </li>
  );
}

function describeError(e: unknown): string {
  if (e instanceof ApiError && e.status === 403) {
    return "You do not have permission to do this. Command not created.";
  }
  return "The command could not be created. Nothing was sent.";
}
