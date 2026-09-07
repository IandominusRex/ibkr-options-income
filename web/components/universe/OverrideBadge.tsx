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
      className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted"
      data-testid="override-badge"
      data-removed={removed}
    >
      <span className="rounded-sm bg-elevated px-1.5 py-0.5 text-content">
        {removed ? "Removed override" : "Override"}
      </span>
      <span>
        {removed ? "removed" : "added"} by {author ?? "n/a"}
        {age ? ` · ${age}` : ""}
      </span>
      <button
        type="button"
        disabled={disabled}
        onClick={onRevert}
        className="text-content underline enabled:hover:text-focus disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
        data-testid="revert-button"
      >
        {removed ? "Revert (add back)" : "Revert"}
      </button>
    </div>
  );
}
