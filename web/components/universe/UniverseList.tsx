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
  return (
    <section className="mb-10" data-testid={`universe-list-${list.name}`}>
      <h2 className="mb-1 text-sm font-medium tracking-wide text-muted">
        {listLabel(list.name)} ({list.entries.length})
      </h2>
      {!list.overridable && (
        <p className="mb-3 text-xs text-muted" data-testid={`readonly-note-${list.name}`}>
          Managed in config/universe.yaml. No add or remove control here.
        </p>
      )}
      {list.entries.length === 0 ? (
        <p className="text-sm text-muted">None</p>
      ) : (
        <ul className="divide-y divide-border">
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
      {list.overridable && (
        <div className="mt-3">
          <AddSymbol listName={list.name as "would_own" | "watchlist"} drainHealthy={drainHealthy} />
        </div>
      )}
    </section>
  );
}

function listLabel(name: string): string {
  switch (name) {
    case "indexes":
      return "Indexes";
    case "watchlist":
      return "Watchlist";
    case "would_own":
      return "Would own - CSP allowlist";
    case "actively_wheeling":
      return "Actively wheeling";
    default:
      return name;
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
    <li className="py-2">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href={`/stock/${entry.symbol}`}
          className={
            "tabular font-mono text-sm hover:text-focus focus-visible:ring-focus " +
            (entry.removed ? "text-muted line-through" : "text-content")
          }
        >
          {entry.symbol}
        </Link>
        {sector && <span className="text-xs text-muted">{sector}</span>}
        {listName === "would_own" && !entry.removed && (
          wheeling?.has(entry.symbol) ? (
            <span
              className="rounded-sm bg-elevated px-1.5 py-0.5 text-xs text-content"
              data-testid={`wheeling-tag-${entry.symbol}`}
            >
              wheeling
            </span>
          ) : (
            <span
              className="rounded-sm bg-elevated px-1.5 py-0.5 text-xs text-muted"
              data-testid={`dip-watch-tag-${entry.symbol}`}
            >
              dip-watch
            </span>
          )
        )}
        {band != null && <span className="text-xs text-unknown">band {band.toFixed(2)}</span>}

        {showPlainRemove && (
          <button
            type="button"
            disabled={inFlight}
            onClick={() => fire("remove")}
            className="ml-auto rounded-sm border border-border bg-background px-2 py-1 text-xs text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
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
        <p
          className="mt-1 text-xs text-loss"
          role="alert"
          data-testid={`entry-error-${entry.symbol}`}
        >
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
