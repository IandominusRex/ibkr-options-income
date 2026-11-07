"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import {
  submitUniverseCommand,
  useCommandStatus,
  type CommandStatus,
} from "@/lib/commands";
import { CommandReceipt } from "@/components/options/CommandReceipt";
import { Card } from "@/components/ui/Card";
import { OverrideBadge } from "./OverrideBadge";
import { AddSymbol } from "./AddSymbol";
import type { UniverseEntry, UniverseListOut } from "./types";

/**
 * One `UniverseListOut` section (M7 Task 7.5): a heading with the entry
 * count, one row per entry, and - only for the two overridable lists
 * (`would_own`, `watchlist`) - an `AddSymbol` control below the entries.
 *
 * `indexes` and `actively_wheeling` render read-only: every entry is plain
 * (the backend never attaches override provenance to a non-overridable
 * list's entries), no add or remove control renders at all, and the section
 * carries one line of text noting it is managed in `config/universe.yaml` -
 * shown, not hidden, per the milestone's "more honest than hiding them"
 * ruling. `overridable` is also checked locally before rendering any control
 * (defence in depth, matching the backend's own discipline), even though the
 * two non-overridable lists never carry `overridden: true` entries in
 * practice.
 *
 * Web overhaul Part 6 restyled it in place: each list is a white Card with a
 * 17px title, the count at the right and one line saying what the list is
 * for; rows are hairline-separated; the tags are status words; Remove is a
 * quiet 44px button on a phone. The behaviour, the test ids and the command
 * flow are unchanged.
 */
export function UniverseList({
  list,
  sectors,
  strikeBands,
  drainHealthy = true,
  activelyWheeling,
}: {
  list: UniverseListOut;
  sectors: Record<string, string>;
  strikeBands: Record<string, number>;
  drainHealthy?: boolean;
  /**
   * Symbols from the `actively_wheeling` list's entries, used only when
   * `list.name === "would_own"` to tell the two `would_own` tiers apart at a
   * glance (pre-M7 behaviour, restored): "wheeling" for a symbol also being
   * actively wheeled, "dip-watch" for one that is not. Ignored for every
   * other list.
   */
  activelyWheeling?: Set<string>;
}) {
  const titleId = `universe-${list.name}-title`;
  return (
    <Card aria-labelledby={titleId} data-testid={`universe-list-${list.name}`}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 id={titleId} className="text-[1.0625rem] font-bold">
          {listLabel(list.name)}
        </h2>
        <span className="tabular shrink-0 text-[0.8125rem] text-muted">
          {list.entries.length === 1 ? "1 name" : `${list.entries.length} names`}
        </span>
      </div>
      <p className="mt-1 text-[0.8125rem] text-muted">{listPurpose(list.name)}</p>
      {!list.overridable && (
        <p className="mt-1 text-[0.8125rem] text-muted" data-testid={`readonly-note-${list.name}`}>
          Managed in config/universe.yaml. No add or remove control here.
        </p>
      )}
      {list.overridable && (
        <div className="mt-3">
          <AddSymbol listName={list.name as "would_own" | "watchlist"} drainHealthy={drainHealthy} />
        </div>
      )}
      {list.entries.length === 0 ? (
        <p className="mt-3 text-sm">None</p>
      ) : (
        <ul className="mt-2">
          {list.entries.map((entry) => (
            <EntryRow
              key={entry.symbol}
              entry={entry}
              listName={list.name}
              overridable={list.overridable}
              sector={sectors[entry.symbol]}
              band={strikeBands[entry.symbol]}
              drainHealthy={drainHealthy}
              wheeling={list.name === "would_own" ? activelyWheeling : undefined}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

function listLabel(name: string): string {
  switch (name) {
    case "indexes":
      return "Indexes";
    case "watchlist":
      return "Watchlist";
    case "would_own":
      return "Would own";
    case "actively_wheeling":
      return "Actively wheeling";
    default:
      return name;
  }
}

/** One line on what a list is for, in the operator's terms. */
function listPurpose(name: string): string {
  switch (name) {
    case "indexes":
      return "Tracked for nightly IV and price history, and shown on the console. Being here selects no trade.";
    case "watchlist":
      return "Tracked for nightly IV and price history, and shown on the console. Being here selects no trade and does not allow a put; only Would own does.";
    case "would_own":
      return "The cash-secured-put allowlist: the system may sell puts on these names, so it may be assigned their shares.";
    case "actively_wheeling":
      return "The names the wheel is working now.";
    default:
      return "";
  }
}

function EntryRow({
  entry,
  listName,
  overridable,
  sector,
  band,
  drainHealthy,
  wheeling,
}: {
  entry: UniverseEntry;
  listName: string;
  overridable: boolean;
  sector?: string;
  band?: number;
  drainHealthy: boolean;
  /** `actively_wheeling` symbols, passed only for the `would_own` list (see UniverseList). */
  wheeling?: Set<string>;
}) {
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const qc = useQueryClient();

  // Poll every 2s while pending; stop once terminal (lib/commands.ts).
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  useEffect(() => {
    if (current && current.status !== "pending") {
      qc.invalidateQueries({ queryKey: ["universe"] });
    }
  }, [current, qc]);

  const inFlight = submitting || (current != null && current.status === "pending");

  async function fire(action: "add" | "remove") {
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitUniverseCommand(action, listName, entry.symbol);
      setCommand(resp);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setSubmitting(false);
    }
  }

  // Defence in depth: overridable is checked again even though the backend
  // never marks a non-overridable list's entries as overridden.
  const showOverrideBadge = entry.overridden && overridable;
  const showPlainRemove = overridable && !entry.overridden;

  return (
    <li className="border-t border-border py-2 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link
          href={`/stock/${entry.symbol}`}
          className={
            "tabular inline-flex min-h-11 items-center font-bold underline-offset-2 hover:underline md:min-h-8 " +
            (entry.removed ? "text-muted line-through" : "text-content")
          }
        >
          {entry.symbol}
        </Link>
        {sector && <span className="text-[0.8125rem] text-muted">{sector}</span>}
        {listName === "would_own" && !entry.removed && (
          wheeling?.has(entry.symbol) ? (
            <span
              className="rounded-[6px] bg-sunk px-2 py-px text-xs font-semibold tracking-[0.04em] text-content"
              data-testid={`wheeling-tag-${entry.symbol}`}
            >
              Wheeling
            </span>
          ) : (
            <span
              className="rounded-[6px] bg-sunk px-2 py-px text-xs font-semibold tracking-[0.04em] text-muted"
              data-testid={`dip-watch-tag-${entry.symbol}`}
            >
              Dip-watch
            </span>
          )
        )}
        {band != null && <span className="tabular text-[0.8125rem] text-muted">{`Strike band ${band.toFixed(2)}`}</span>}

        {showPlainRemove && (
          <button
            type="button"
            disabled={inFlight}
            onClick={() => fire("remove")}
            className="ml-auto inline-flex min-h-11 items-center rounded-full px-3 text-[0.8125rem] font-semibold text-muted enabled:hover:bg-sunk enabled:hover:text-content disabled:opacity-50 md:min-h-8"
            data-testid={`remove-${entry.symbol}`}
          >
            Remove
          </button>
        )}
      </div>

      {showOverrideBadge && (
        <OverrideBadge
          author={entry.created_by}
          timestamp={entry.created_at}
          removed={entry.removed}
          disabled={inFlight}
          onRevert={() => fire(entry.removed ? "add" : "remove")}
        />
      )}

      {error && (
        <p className="mt-1 text-sm" role="alert" data-testid={`entry-error-${entry.symbol}`}>
          {error}
        </p>
      )}

      {current && <CommandReceipt command={current} order={null} drainHealthy={drainHealthy} />}
    </li>
  );
}

function describeError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) {
      return "You do not have permission to do this. Command not created.";
    }
    if (e.status === 404) {
      return "That symbol is not recognized. Command not created.";
    }
    if (e.status === 409) {
      return "This symbol is actively wheeled and cannot be removed from would own right now.";
    }
  }
  return "The command could not be created. Nothing was sent.";
}
