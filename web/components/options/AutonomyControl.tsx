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
import { ConfirmAction } from "./ConfirmAction";
import { CommandReceipt } from "./CommandReceipt";

// A singleton control (ControlsStrip mounts one AutonomyControl), so a fixed
// key is safe — unlike the per-item decide flows (DecideControls/ShortsRow/
// AssessedRow), which namespace by approval id / position symbol / candidate
// id. Shares the same `ibkr-options:command:` prefix (lib/commands.ts).
const STORAGE_KEY = "autonomy";

/**
 * The autonomy rung control (P2 M6 Task 6.3).
 *
 * The four rungs render from the API's `rungs` array, never hardcoded — the
 * ladder is the server's to define. A rung change is click-through confirmed
 * showing the current and target rungs, because a rung change alters what the
 * system does without asking (weight table: heavier than approve's summary,
 * lighter than resume's typed word — it does not re-arm execution by itself).
 *
 * A promotion refused by the evidence gate renders through the receipt as a
 * plain failed command with `promotion refused` and the blockers in the
 * detail — the web is not the rung ladder's back door, and the receipt says
 * why in words rather than hiding the refusal.
 */
export function AutonomyControl({
  autonomy,
  rungs,
  drainHealthy = true,
}: {
  autonomy: { level: string; label: string };
  rungs: { level: string; label: string }[];
  drainHealthy?: boolean;
}) {
  const [target, setTarget] = useState<string | null>(null);
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveStep, setLiveStep] = useState<CommandStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Restore an in-flight rung change (including one awaiting the live second
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
      qc.invalidateQueries({ queryKey: ["options", "controls"] });
    }
  }, [current, qc]);

  // liveStep counts as in flight too — see DecideControls's identical fix:
  // there is no command id to poll until the live confirmation is released,
  // so `current` alone would leave the autonomy select clickable while that
  // dialog is already open.
  const inFlight =
    submitting || liveStep != null || (current != null && current.status === "pending");

  async function onConfirm() {
    const level = target;
    setTarget(null);
    if (level === null) return;
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitCommand("set_autonomy", { level });
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

  const targetLabel = rungs.find((r) => r.level === target)?.label ?? target ?? "";

  return (
    <div data-testid="autonomy-control">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted">Autonomy</span>
        <select
          aria-label="Autonomy rung"
          value={autonomy.level}
          disabled={inFlight}
          onChange={(e) => {
            if (e.target.value !== autonomy.level) setTarget(e.target.value);
          }}
          className="rounded-sm border border-border bg-background px-2 py-1 text-sm text-content focus-visible:ring-focus disabled:cursor-default disabled:opacity-50"
          data-testid="autonomy-select"
        >
          {rungs.map((r) => (
            <option key={r.level} value={r.level} label={r.label} />
          ))}
        </select>
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

      {target && (
        <ConfirmAction
          title="Change the autonomy rung"
          summary={
            <span>
              Move the autonomy rung from {autonomy.label} to {targetLabel}. This
              changes what the system may do without asking you first. A promotion can
              be refused by the evidence gate; the receipt will say so in words.
            </span>
          }
          confirmLabel={`Set ${targetLabel}`}
          onConfirm={onConfirm}
          onCancel={() => setTarget(null)}
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