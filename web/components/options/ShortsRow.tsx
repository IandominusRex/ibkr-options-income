"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import {
  confirmCommand,
  loadPersistedCommand,
  savePersistedCommand,
  submitCommand,
  useCommandStatus,
  type CommandStatus,
} from "@/lib/commands";
import { UNKNOWN, relativeAge } from "@/lib/format";
import type { ShortPosition } from "./types";
import { ConfirmAction } from "./ConfirmAction";
import { CommandReceipt } from "./CommandReceipt";

/**
 * One open short option position's table row, extracted from `ShortsTable` so the
 * roll control (P2 M5 Task 5.2) has somewhere to live without turning `ShortsTable`
 * into a second copy of the decide flow.
 *
 * The roll flow mirrors `AssessedRow`'s promote control exactly (M4 Task 4.3): a
 * `confirming` state gates a `<ConfirmAction/>` before any request,
 * `submitCommand("roll_request", { position_symbol })` fires once on confirm, a
 * live-mode response routes through a second, distinctly labelled LIVE
 * confirmation, and `useCommandStatus` polls the result until terminal.
 *
 * Two receipts are special-cased per the milestone:
 * - `no_qualifying_roll` renders as a plain sentence, not red failed chrome — it
 *   is a legitimate answer, not an error. `CommandReceipt` gains an optional
 *   `plainReasons` prop for this; default absent, so every existing receipt is
 *   byte-identical.
 * - `roll_already_working` renders the standard failed receipt plus a link to the
 *   in-flight approval (`result.detail.approval_id`), so the operator can act on
 *   the proposal the monitor already raised.
 * - On success (`applied`), the receipt links to the new approval.
 *
 * The control is labelled "Propose a roll", not "Roll" — the button does not roll
 * the position, and the copy must not imply it does (client rule 3 applied to a
 * verb).
 */
export function ShortsRow({
  short,
  drainHealthy = true,
}: {
  short: ShortPosition;
  drainHealthy?: boolean;
}) {
  // Namespaced so this never collides with a <DecideControls/> approval id or
  // an <AssessedRow/> promote entry in the same localStorage (lib/commands.ts).
  const storageKey = `short:${short.position_symbol}`;

  const [confirming, setConfirming] = useState(false);
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveStep, setLiveStep] = useState<CommandStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Restore an in-flight roll proposal (including one awaiting the live second
  // confirmation) after a page reload — mount-only, so it doesn't clobber a
  // command this row is actively progressing through.
  useEffect(() => {
    const persisted = loadPersistedCommand(storageKey);
    if (!persisted) return;
    if (persisted.needs_confirmation) setLiveStep(persisted);
    else setCommand(persisted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const qc = useQueryClient();

  // Poll every 2s while pending; stop once terminal (lib/commands.ts).
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  // Mirror the in-flight command to localStorage — see the mount-only restore
  // effect above and lib/commands.ts's persistence layer.
  useEffect(() => {
    if (liveStep) {
      savePersistedCommand(storageKey, liveStep);
    } else if (current && current.status === "pending") {
      savePersistedCommand(storageKey, current);
    } else {
      savePersistedCommand(storageKey, null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, liveStep, current]);

  useEffect(() => {
    if (current && current.status !== "pending") {
      // A roll proposal raises an approval → invalidate the approvals list so the
      // new card appears on the next poll. Shorts data itself is unchanged by a
      // proposal (no order, no fill), so the shorts query is left alone.
      qc.invalidateQueries({ queryKey: ["options", "approvals"] });
    }
  }, [current, qc]);

  // liveStep counts as in flight too — see DecideControls's identical fix: there
  // is no command id to poll until the live confirmation is released, so
  // `current` alone would leave "Propose a roll" clickable while that dialog is
  // already open.
  const inFlight =
    submitting || liveStep != null || (current != null && current.status === "pending");

  async function onConfirm() {
    setConfirming(false);
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitCommand("roll_request", {
        position_symbol: short.position_symbol,
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

  const result = current?.result as
    | { reason?: string; approval_id?: number | null; detail?: { approval_id?: number | null } }
    | null;
  const reason = current?.status === "failed" ? result?.reason : undefined;
  const successApprovalId =
    current?.status === "applied" ? (result?.approval_id ?? null) : null;
  const workingApprovalId =
    reason === "roll_already_working" ? (result?.detail?.approval_id ?? null) : null;

  return (
    <>
      <tr key={short.position_symbol}>
        <td className="py-2">
          <div className="font-mono text-xs text-content">
            {short.underlying} {short.strike.toFixed(2)} {short.right}
          </div>
          <div className="text-xs text-muted">{short.position_symbol}</div>
        </td>
        <td className="py-2 tabular text-content">
          {short.dte != null ? short.dte : UNKNOWN}
        </td>
        <td className="py-2 tabular text-content">{short.contracts}</td>
        <td className="py-2 tabular">
          {short.mark != null ? `$${short.mark.toFixed(2)}` : UNKNOWN}
        </td>
        <td className="py-2 tabular">
          {short.unrealized_pnl != null
            ? `$${short.unrealized_pnl.toFixed(0)}`
            : UNKNOWN}
        </td>
        <td className="py-2 tabular text-xs">
          {short.delta != null ? (
            <span className="text-content">
              {short.delta.value != null ? short.delta.value.toFixed(2) : UNKNOWN}
              <span className="ml-1 text-muted">{short.delta.source}</span>
            </span>
          ) : (
            UNKNOWN
          )}
        </td>
        <td className="py-2 text-xs text-muted">
          {short.alerts.length > 0 ? (
            <ul className="space-y-0.5">
              {short.alerts.map((a) => (
                <li key={a.id}>
                  <span className="text-content">{a.trigger_label}</span>
                  <span className="text-muted"> {a.detail}</span>
                  <span className="text-muted"> {relativeAge(a.created_at)} ago</span>
                  {a.claude_recommendation && (
                    <span className="text-muted">
                      {" "}
                      Model opinion (Claude): {a.claude_recommendation}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </td>
        <td className="py-2">
          <button
            type="button"
            disabled={inFlight}
            onClick={() => setConfirming(true)}
            className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
          >
            Propose a roll
          </button>
        </td>
      </tr>

      {(current || error || workingApprovalId != null || successApprovalId != null) && (
        <tr>
          <td colSpan={8} className="pb-3">
            {error && (
              <p className="text-xs text-loss" data-testid="command-error" role="alert">
                {error}
              </p>
            )}

            {current && reason === "no_qualifying_roll" ? (
              <div
                data-testid="command-receipt"
                data-state="answered"
                className="mt-2 rounded-sm border border-border bg-background px-3 py-2 text-xs"
              >
                <p className="flex items-baseline gap-2">
                  <span className="font-medium text-content">No qualifying roll</span>
                  <span className="text-muted">
                    No roll on the current chain clears the roll&apos;s own bounds. That is a
                    real answer, not an error.
                  </span>
                  <span className="ml-auto font-mono text-muted">intent {current.id}</span>
                </p>
              </div>
            ) : current ? (
              <CommandReceipt
                command={current}
                order={null}
                drainHealthy={drainHealthy}
              />
            ) : null}

            {workingApprovalId != null && (
              <p className="mt-1 text-xs">
                <Link
                  href={`/options/${workingApprovalId}`}
                  className="text-content underline hover:text-focus focus-visible:ring-focus"
                >
                  View the roll already in flight
                </Link>
              </p>
            )}

            {successApprovalId != null && (
              <p className="mt-1 text-xs">
                <Link
                  href={`/options/${successApprovalId}`}
                  className="text-content underline hover:text-focus focus-visible:ring-focus"
                >
                  View approval
                </Link>
              </p>
            )}
          </td>
        </tr>
      )}

      {liveStep && (
        <ConfirmAction
          title={`Confirm LIVE ${liveStep.kind}`}
          summary={
            <span>
              This is the second, mandatory confirmation for live trading. The first confirmation
              queued the intent; releasing it now lets the trading service apply it. The
              execution-time [CONFIRM LIVE] Telegram step still fires afterwards.
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
          title="Propose a roll"
          summary={
            <span>
              The system will price a roll for {short.underlying}{" "}
              {short.strike.toFixed(2)} {short.right} and raise it as a pending approval.
              Nothing executes until you approve that proposal. The roll&apos;s own debit and
              delta-reduction bounds decide whether one qualifies.
            </span>
          }
          confirmLabel="Propose a roll"
          onConfirm={onConfirm}
          onCancel={() => setConfirming(false)}
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