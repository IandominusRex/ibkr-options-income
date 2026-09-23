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
import { relativeAge } from "@/lib/format";

// A singleton control (ControlsStrip mounts one HaltControl), so a fixed key
// is safe — unlike the per-item decide flows (DecideControls/ShortsRow/
// AssessedRow), which namespace by approval id / position symbol / candidate
// id. Shares the same `ibkr-options:command:` prefix (lib/commands.ts).
const STORAGE_KEY = "halt-resume";
import { ConfirmAction } from "./ConfirmAction";
import { CommandReceipt } from "./CommandReceipt";

/**
 * The halt and resume controls (P2 M6 Task 6.3).
 *
 * The confirmation weights are deliberately NOT mirror images, and the tests
 * are named so a later reader does not "fix" this:
 *
 * - `halt` is ONE CLICK, no dialog. Speed is the feature: a halt you had to
 *   confirm twice is a halt that came too late. It is trivially reversible by
 *   resume.
 * - `resume` requires the typed word RESUME through ConfirmAction. Releasing
 *   the kill switch re-arms execution; that deserves deliberation in a way
 *   halting does not.
 *
 * A halt from the browser is a control-plane change with no order-poll loop
 * to report it later, so the drain handler notifies Telegram; the banner here
 * is the console-side half of "visible wherever the operator is".
 */
export function HaltControl({
  halted,
  haltReason,
  haltedAt,
  drainHealthy = true,
}: {
  halted: boolean;
  haltReason: string | null;
  haltedAt: string | null;
  drainHealthy?: boolean;
}) {
  const [resuming, setResuming] = useState(false);
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveStep, setLiveStep] = useState<CommandStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Restore an in-flight halt/resume (including one awaiting the live second
  // confirmation) after a page reload — mount-only, so it doesn't clobber a
  // command this control is actively progressing through.
  useEffect(() => {
    const persisted = loadPersistedCommand(STORAGE_KEY);
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
      savePersistedCommand(STORAGE_KEY, liveStep);
    } else if (current && current.status === "pending") {
      savePersistedCommand(STORAGE_KEY, current);
    } else {
      savePersistedCommand(STORAGE_KEY, null);
    }
  }, [liveStep, current]);

  useEffect(() => {
    if (current && current.status !== "pending") {
      // A control change flips system_settings the /options/controls read
      // renders; invalidate it so the strip and banner move on the next poll
      // rather than up to 30s later.
      qc.invalidateQueries({ queryKey: ["options", "controls"] });
    }
  }, [current, qc]);

  // liveStep counts as in flight too — see DecideControls's identical fix:
  // there is no command id to poll until the live confirmation is released,
  // so `current` alone would leave Halt/Resume clickable while that dialog is
  // already open.
  const inFlight =
    submitting || liveStep != null || (current != null && current.status === "pending");

  async function fire(kind: "halt" | "resume") {
    setError(null);
    setSubmitting(true);
    try {
      const resp =
        kind === "halt"
          ? await submitCommand("halt", {})
          : await submitCommand("resume", {});
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

  // Halt: one click, no dialog. This is the deliberate asymmetry — see the
  // component docstring and the milestone's weight table.
  async function onHalt() {
    await fire("halt");
  }

  async function onResumeConfirmed() {
    setResuming(false);
    await fire("resume");
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

  return (
    <div data-testid="halt-control">
      <div className="flex items-center gap-2">
        {halted ? (
          <button
            type="button"
            disabled={inFlight}
            onClick={() => setResuming(true)}
            className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
            data-testid="resume-button"
          >
            Resume
          </button>
        ) : (
          <button
            type="button"
            disabled={inFlight}
            onClick={onHalt}
            className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
            data-testid="halt-button"
          >
            Halt
          </button>
        )}
        {halted && (
          <span className="text-xs text-muted">
            halted {haltedAt ? relativeAge(haltedAt) : "at an unknown time"}
            {haltReason ? ` - ${haltReason}` : ""}
          </span>
        )}
      </div>

      {error && (
        <p className="mt-2 text-xs text-loss" data-testid="command-error" role="alert">
          {error}
        </p>
      )}

      {current && <CommandReceipt command={current} order={null} drainHealthy={drainHealthy} />}

      {liveStep && (
        <ConfirmAction
          title={`Confirm LIVE ${liveStep.kind}`}
          summary={
            <span>
              This is the second, mandatory confirmation for live trading. The first
              confirmation queued the intent; releasing it now lets the trading service
              apply it. The execution-time [CONFIRM LIVE] Telegram step still fires
              afterwards.
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

      {resuming && (
        <ConfirmAction
          title="Resume execution"
          summary={
            <span>
              This releases the kill switch and re-arms order execution. Queued orders
              resume on the next poll cycle. Halting again is one click.
            </span>
          }
          confirmLabel="Resume"
          requireTypedWord="RESUME"
          onConfirm={onResumeConfirmed}
          onCancel={() => setResuming(false)}
        />
      )}
    </div>
  );
}

function describeError(e: unknown): string {
  if (e instanceof ApiError && e.status === 403) {
    return "You do not have permission to do this. Command not created.";
  }
  return "The command could not be created. Nothing was sent.";
}