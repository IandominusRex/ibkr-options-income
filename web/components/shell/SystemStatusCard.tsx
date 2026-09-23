"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import clsx from "clsx";
import { apiFetch } from "@/lib/api";
import { SystemLogPanel } from "./SystemLogPanel";

export type SystemState = "ok" | "degraded" | "unknown" | "down";

export type SystemRow = {
  key: string;
  label: string;
  state: SystemState;
  detail: string;
  log_key: string | null;
};

type SystemStatusResponse = { as_of: string; rows: SystemRow[] };

function dotClass(state: SystemState): string {
  switch (state) {
    case "ok":
      return "bg-gain";
    case "down":
      return "border border-loss";
    case "degraded":
    case "unknown":
      return "hatch";
  }
}

export function SystemStatusCard() {
  const [openRow, setOpenRow] = useState<SystemRow | null>(null);
  const { data, isError } = useQuery({
    queryKey: ["system", "status"],
    queryFn: () => apiFetch<SystemStatusResponse>("/system/status"),
    refetchInterval: 20_000,
  });

  return (
    <div className="border-t border-border px-3 py-3">
      <div className="mb-2 font-mono text-xs text-muted">System status</div>
      {isError ? (
        <p className="text-xs text-unknown">Status unavailable</p>
      ) : (
        <ul className="space-y-1.5">
          {(data?.rows ?? []).map((row) => (
            <li key={row.key}>
              <button
                type="button"
                disabled={row.log_key === null}
                onClick={() => setOpenRow(row)}
                className="flex w-full items-center gap-2 rounded-sm px-1 py-0.5 text-left enabled:hover:bg-surface disabled:cursor-default"
              >
                <span
                  data-testid="status-dot"
                  data-state={row.state}
                  className={clsx("h-2 w-2 shrink-0 rounded-full", dotClass(row.state))}
                />
                <span className="flex-1 truncate text-xs text-content">{row.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {openRow && <SystemLogPanel row={openRow} onClose={() => setOpenRow(null)} />}
    </div>
  );
}
