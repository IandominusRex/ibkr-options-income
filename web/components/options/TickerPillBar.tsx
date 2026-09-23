"use client";

import type { ApprovalSummary } from "./types";

/**
 * A scrollable row of ticker pills below the Approvals list — one per
 * distinct `underlying` present in the (visible) approvals list, with its
 * count. Picking a pill filters the Approvals list down to that ticker
 * (the parent owns the selection and composes it into `<ApprovalsList
 * filter>`); picking the same pill again clears the filter. Purely
 * presentational — no fetch of its own, so it always reflects exactly what
 * the Approvals tab is showing, never a separate dataset that can be empty
 * or stale when the approvals list itself is not.
 */
export function TickerPillBar({
  approvals,
  selected,
  onSelect,
}: {
  approvals: ApprovalSummary[];
  selected: string | null;
  onSelect: (symbol: string | null) => void;
}) {
  const counts = new Map<string, number>();
  for (const a of approvals) {
    counts.set(a.underlying, (counts.get(a.underlying) ?? 0) + 1);
  }

  if (counts.size === 0) return null;

  return (
    <div className="flex gap-2 overflow-x-auto pb-1" data-testid="ticker-pill-bar">
      {[...counts.entries()].map(([symbol, count]) => {
        const active = symbol === selected;
        return (
          <button
            key={symbol}
            type="button"
            onClick={() => onSelect(active ? null : symbol)}
            aria-pressed={active}
            className={
              "flex shrink-0 items-center gap-2 rounded-full border px-3 py-1 text-xs " +
              (active
                ? "border-focus text-content"
                : "border-border text-muted hover:text-content")
            }
          >
            <span className="font-mono">{symbol}</span>
            <span className="tabular">{count}</span>
          </button>
        );
      })}
    </div>
  );
}
