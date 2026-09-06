"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";
import type { ControlsResponse } from "./types";

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
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border border-border bg-surface px-4 py-3 text-sm">
      <ControlPill label="Mode" value={data.mode} />
      <ControlPill
        label="Autonomy"
        value={data.autonomy.label}
      />
      <ControlPill
        label="Halt"
        value={data.halted ? "ENGAGED" : "off"}
        danger={data.halted}
      />
      {data.halted && data.halt_reason && (
        <span className="text-xs text-muted">{data.halt_reason}</span>
      )}
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
      <ControlPill
        label="Pending"
        value={String(data.pending_commands)}
      />
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