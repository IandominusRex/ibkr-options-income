"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

type Hit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
type SearchResponse = { as_of: string; query: string; results: Hit[] };

/**
 * Controlled if `open`/`onOpenChange` are passed (the visible search-bar
 * trigger on the home page owns the state so it can open the same modal);
 * otherwise falls back to managing its own state so ⌘K keeps working
 * anywhere the palette is mounted without a parent wiring it up.
 *
 * Never unmounts on close (it renders `null`, same component instance stays
 * mounted so the global ⌘K listener keeps working) — so unlike
 * `ConfirmAction` (which returns focus to the trigger via an unmount
 * cleanup), this component watches `open` itself: on the true->false edge it
 * clears the search term/results (reopening starts fresh, never shows a
 * stale search from last time) and returns focus to whatever had it when the
 * palette opened. `role="dialog"`/`aria-modal`/a Tab focus trap mirror
 * `ConfirmAction`'s pattern — every overlay in this app traps focus and
 * returns it on close, this one is no exception.
 */
export function CommandPalette({
  open: openProp,
  onOpenChange,
}: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
} = {}) {
  const router = useRouter();
  const [internalOpen, setInternalOpen] = useState(false);
  const open = openProp ?? internalOpen;
  const setOpen = onOpenChange ?? setInternalOpen;
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<Element | null>(null);
  const wasOpen = useRef(false);
  const labelId = useId();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(!open);
      }
      if (e.key === "Escape" && open) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  // The open/close edges: remember the trigger and focus the input on open,
  // reset the search and return focus to the trigger on close. Deliberately
  // NOT the native `autoFocus` prop on the input: that attribute focuses the
  // input during React's DOM-mutation commit, which runs BEFORE this effect —
  // by the time this effect could read `document.activeElement` to capture
  // the trigger, autoFocus would have already overwritten it with the input
  // itself. Focusing the input imperatively here, in the same effect and
  // strictly after the capture, keeps the ordering correct.
  useEffect(() => {
    if (open && !wasOpen.current) {
      triggerRef.current = document.activeElement;
      inputRef.current?.focus();
    } else if (!open && wasOpen.current) {
      setTerm("");
      setHits([]);
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement) trigger.focus();
    }
    wasOpen.current = open;
  }, [open]);

  // Tab focus trap, active only while open — mirrors ConfirmAction exactly.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusables = dialog.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input, [href], [tabindex]:not([tabindex='-1'])",
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    if (!term.trim()) {
      setHits([]);
      return;
    }
    const id = setTimeout(async () => {
      try {
        const data = await apiFetch<SearchResponse>(
          `/research/search?q=${encodeURIComponent(term)}`,
        );
        setHits(data.results);
      } catch {
        setHits([]);
      }
    }, 200);
    return () => clearTimeout(id);
  }, [term]);

  if (!open) return null;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelId}
      className="fixed inset-0 z-50 flex items-start justify-center bg-scrim pt-[15vh]"
    >
      <div className="w-full max-w-xl rounded-lg bg-elevated p-2">
        <label htmlFor={labelId} className="sr-only">
          Search a ticker or company
        </label>
        <input
          id={labelId}
          ref={inputRef}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="Search a ticker or company"
          className="w-full bg-transparent px-3 py-2 font-mono text-sm text-content outline-none placeholder:text-muted"
        />
        <ul className="max-h-80 overflow-y-auto">
          {hits.map((h) => (
            <li key={h.symbol}>
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  router.push(`/stock/${h.symbol}`);
                }}
                className="flex w-full items-baseline gap-3 rounded px-3 py-2 text-left hover:bg-surface focus-visible:bg-surface"
              >
                <span className="tabular font-mono text-sm text-content">{h.symbol}</span>
                <span className="truncate text-sm text-muted">{h.name}</span>
                {h.is_etf && <span className="ml-auto text-[11px] text-muted">ETF</span>}
              </button>
            </li>
          ))}
          {term.trim() && hits.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted">No match</li>
          )}
        </ul>
      </div>
    </div>
  );
}