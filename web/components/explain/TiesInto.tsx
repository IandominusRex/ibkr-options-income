"use client";

import type { TieIn } from "./types";
import { TAB_META } from "./types";

/**
 * "How this ties into the rest of the system" - a short, reasoned link to each related
 * subtab, not just a label. Every panel ends with one of these so the tab never reads as
 * an island; clicking a chip jumps the shell straight there.
 */
export function TiesInto({
  items,
  onNavigate,
}: {
  items: TieIn[];
  onNavigate: (tab: TieIn["tab"]) => void;
}) {
  if (items.length === 0) return null;

  return (
    <div className="mt-8 border-t border-border pt-5">
      <h3 className="mb-3 font-mono text-xs uppercase tracking-wide text-muted">
        Ties into
      </h3>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.tab}>
            <button
              type="button"
              onClick={() => onNavigate(item.tab)}
              className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-md border border-border bg-surface px-3 py-2 text-left text-sm text-muted transition-colors hover:border-focus/60 hover:text-content"
            >
              <span className="font-medium text-content">{TAB_META[item.tab].label}</span>
              <span>{item.reason}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
