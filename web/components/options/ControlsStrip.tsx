"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";
import type { ControlsResponse } from "./types";
import { AutonomyControl } from "./AutonomyControl";
import { HaltControl } from "./HaltControl";

/**
 * The controls strip (M2 Task 2.6, read-only then; M6 Task 6.3 makes it live).
 *
 * The halted state must be unmissable: when `halted` is true a banner renders
 * at the top of the console, with the reason and the time it was engaged as
 * text. The banner uses fill and text, never colour alone; the same applies
 * to `HaltControl`'s own button, whose label changes between "Halt" and
 * "Resume" rather than relying on a colour swap.
 *
 * `drain_healthy: false` renders "the trading service is not draining
 * commands" beside every control: a halt queued but never picked up is this
 * milestone's worst case, and the operator must know immediately — a receipt
 * alone would only say it after a click.
 */
export function ControlsStrip() {
  const { data } = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  if (!data) {
    return <p className="text-sm text-muted">Loading controls</p>;
  }

  return (
    <div className="flex flex-col gap-3" data-testid="controls-strip">
      {data.halted && (
        <div
          data-testid="halted-banner"
          className="rounded-md border border-border bg-surface px-4 py-3"
        >
          <p className="text-sm font-medium text-content">
            Execution is HALTED
            {data.halt_reason ? `: ${data.halt_reason}` : ""}
          </p>
          <p className="mt-1 text-xs text-muted">
            Engaged{" "}
            {data.halted_at
              ? relativeAge(data.halted_at)
              : "at an unknown time (no web halt command recorded)"}
            . No new orders will be queued or transmitted; profit-take closes still
            run. Use Resume below to release.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border border-border bg-surface px-4 py-3 text-sm">
        <ControlPill label="Mode" value={data.mode} />
        <AutonomyControl autonomy={data.autonomy} rungs={data.rungs} drainHealthy={data.drain_healthy} />
        <HaltControl
          halted={data.halted}
          haltReason={data.halt_reason}
          haltedAt={data.halted_at}
          drainHealthy={data.drain_healthy}
        />
        <ControlPill
          label="Drain"
          value={data.drain_healthy ? "healthy" : "unhealthy"}
          danger={!data.drain_healthy}
        />
        {!data.drain_healthy && (
          <span className="text-xs text-muted">
            {data.drain_last_seen
              ? `last seen ${relativeAge(data.drain_last_seen)}`
              : "the command drain has never run"}
          </span>
        )}
        <ControlPill label="Pending" value={String(data.pending_commands)} />
      </div>

      {!data.drain_healthy && (
        <p
          className="rounded-md border border-border bg-surface px-4 py-2 text-xs text-content"
          data-testid="drain-dead-warning"
        >
          the trading service is not draining commands
          {data.drain_last_seen
            ? ` (last seen ${relativeAge(data.drain_last_seen)})`
            : " (it has never run)"}
          . A click below queues an intent; it will not be applied until the drain
          is back.
        </p>
      )}
    </div>
  );
}

function ControlPill({
  label,
  value,
  danger,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <span className="tabular">
      <span className="text-xs text-muted">{label} </span>
      <span className={danger ? "text-loss" : "text-content"}>{value}</span>
    </span>
  );
}