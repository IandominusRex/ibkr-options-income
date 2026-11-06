"use client";

import { relativeAge } from "@/lib/format";

/**
 * The provenance badge for an overridden universe entry (M7 Task 7.5).
 *
 * An override can run in two directions and `removed` tells them apart: an
 * operator added a symbol (or re-affirmed a base one), or an operator removed
 * a YAML-base symbol. Either way the row this badge sits under stays visible
 * - never hidden, per the "the YAML base value stays visible underneath"
 * requirement - this badge only says who acted, roughly when, and offers a
 * way back through `onRevert`.
 *
 * `author` and `timestamp` are `created_by`/`created_at` off the entry, both
 * nullable on the wire; a missing one renders "n/a", never a fabricated name
 * or date.
 */
export function OverrideBadge({
  author,
  timestamp,
  removed,
  onRevert,
  disabled = false,
}: {
  author: string | null;
  timestamp: string | null;
  removed: boolean;
  onRevert: () => void;
  disabled?: boolean;
}) {
  const age = timestamp ? relativeAge(timestamp) : "";

  return (
    <div
      className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] text-muted"
      data-testid="override-badge"
      data-removed={removed}
    >
      <span className="rounded-[6px] bg-sunk px-2 py-px text-xs font-semibold tracking-[0.04em] text-content">
        {removed ? "Removed override" : "Override"}
      </span>
      <span>
        {removed ? "removed" : "added"} by {author ?? <span className="hatch px-1 text-unknown">n/a</span>}
        {age ? ` · ${age}` : ""}
      </span>
      <button
        type="button"
        disabled={disabled}
        onClick={onRevert}
        className="inline-flex min-h-11 items-center font-semibold text-content underline underline-offset-2 enabled:hover:text-muted disabled:cursor-default disabled:opacity-50 md:min-h-0"
        data-testid="revert-button"
      >
        {removed ? "Revert (add back)" : "Revert"}
      </button>
    </div>
  );
}
