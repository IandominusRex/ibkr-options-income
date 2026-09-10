"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { submitCommand, useCommandStatus, type CommandStatus } from "@/lib/commands";
import { CommandReceipt } from "@/components/options/CommandReceipt";

/**
 * The page-level manual refresh control (P3-P4 M3 Task 3.5), mounted in
 * `PortfolioShell`'s header so it is visible regardless of which tab is
 * active. Fires `POST /commands` with `kind: "refresh"` -
 * `src/notify/command_drain.py`'s `_refresh` handler (P3/P4 M1 Task 1.4,
 * documented in `docs/web/commands.md`'s `refresh` entry): captures live
 * positions and account values now and appends one `portfolio_snapshots`
 * row.
 *
 * One click, no confirmation dialog - mirrors `HaltControl`'s halt button
 * and `AddSymbol`'s watchlist-add path. `docs/web/commands.md` states it
 * plainly: "No confirmation needed. A refresh creates no candidate, no
 * approval, and no order." It never returns `needs_confirmation: true`, so
 * there is no live-mode second-confirmation step to build here, matching how
 * `AddSymbol` omits that step for `universe_add`/`universe_remove` for the
 * same documented reason.
 *
 * `broker_unavailable` renders as a plain answer through `CommandReceipt`'s
 * `plainReasons` prop, not red failed chrome - the drain not holding a live
 * IB connection when a refresh is asked for is an ordinary state, matching
 * how `no_qualifying_roll` renders on the shorts list.
 *
 * On a terminal status the portfolio queries invalidate under the
 * `["portfolio"]` key prefix - TanStack's default prefix matching catches
 * `["portfolio","summary"]`, `["portfolio","positions"]`,
 * `["portfolio","campaigns",...]` and `["portfolio","calendar",...]` all at
 * once, so whichever tab is open next poll sees the new snapshot `_refresh`
 * just wrote. Reuses P2's command machinery unchanged: `submitCommand`,
 * `useCommandStatus` (which stops polling once the status is terminal -
 * lib/commands.ts's own `TERMINAL` gate), and `CommandReceipt` - no second
 * receipt, poller, or submit helper here.
 */
export function RefreshControl({ drainHealthy = true }: { drainHealthy?: boolean }) {
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const qc = useQueryClient();

  // Poll every 2s while pending; stop once terminal (lib/commands.ts).
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  useEffect(() => {
    if (current && current.status !== "pending") {
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    }
  }, [current, qc]);

  const inFlight = submitting || (current != null && current.status === "pending");

  async function onRefresh() {
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitCommand("refresh", {});
      setCommand(resp);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div data-testid="refresh-control" className="flex items-center gap-2">
      <button
        type="button"
        disabled={inFlight}
        onClick={onRefresh}
        className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
      >
        Refresh
      </button>

      {error && (
        <p className="text-xs text-loss" data-testid="command-error" role="alert">
          {error}
        </p>
      )}

      {current && (
        <CommandReceipt
          command={current}
          order={null}
          drainHealthy={drainHealthy}
          plainReasons={["broker_unavailable"]}
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
