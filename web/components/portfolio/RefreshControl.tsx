"use client";

import clsx from "clsx";
import { RefreshCw } from "lucide-react";
import { CommandReceipt } from "@/components/options/CommandReceipt";
import { Button } from "@/components/ui/Button";
import { useBrokerRefresh } from "./useBrokerRefresh";

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
 * The command flow itself is `useBrokerRefresh`, shared with the refresh icon on Home and the
 * position pages. It reads `GET /options/controls` for the real `drain_healthy`, so a click while
 * `approval_service` is down states "the trading service is not draining commands" instead of
 * rendering "Queued" and polling forever.
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
export function RefreshControl() {
  const { refresh, inFlight, current, error, drainHealthy } = useBrokerRefresh("portfolio");

  return (
    <div data-testid="refresh-control" className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {/* Secondary, not lime: a refresh reads the broker and writes one snapshot; it decides nothing. */}
      <Button variant="secondary" disabled={inFlight} onClick={refresh}>
        <RefreshCw size={16} strokeWidth={2.25} aria-hidden="true" className={clsx(inFlight && "motion-safe:animate-spin")} />
        Refresh
      </Button>

      {error && (
        <p className="text-[0.8125rem] text-loss" data-testid="command-error" role="alert">
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
