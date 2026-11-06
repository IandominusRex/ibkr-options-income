"use client";

import clsx from "clsx";
import { Search } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { StatusWord } from "@/components/ui/StatusWord";
import { matchPages } from "@/features/search/pages";
import { apiFetch } from "@/lib/api";
import { OPEN_SEARCH_EVENT } from "@/lib/search";

type Hit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
type SearchResponse = { as_of: string; query: string; results: Hit[] };

/** One row of the list: a page of the console or a ticker's stock page. */
type Option = { key: string; group: "Pages" | "Tickers"; href: string; title: string; sub: string; etf: boolean };

/** What the ticker search last answered, for the term it answered (so a stale answer is never shown). */
type Answer = { term: string; hits: Hit[]; failed: boolean };

/**
 * The console's search (web overhaul Part 6): one dialog, mounted once in the root layout, that finds
 * a ticker (`GET /research/search`, a pick opens `/stock/SYM`) or one of the console's own pages
 * (`features/search/pages.ts`, no request). ⌘K or Ctrl+K toggles it anywhere; the rail, More and
 * Research open it through `openSearch()` (`lib/search.ts`). Pages are listed above tickers.
 *
 * The input is a combobox: the arrow keys move through the results, Enter opens the active one, Escape
 * closes, and a tap on the scrim or Close (phones) closes. It reads and navigates; it sends nothing.
 *
 * Controlled if `open`/`onOpenChange` are passed, otherwise it keeps its own state. It never unmounts on
 * close (it renders `null`), so the shortcut and the open event keep working; it watches the open edge
 * itself instead: on close it clears the search (reopening starts fresh) and returns focus to whatever
 * had it when it opened. The input is focused imperatively in that same effect, after the capture, not
 * with `autoFocus` (which would steal focus before the trigger could be remembered). Tab is trapped
 * inside, as `ConfirmAction` traps it.
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
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [active, setActive] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<Element | null>(null);
  const wasOpen = useRef(false);
  const titleId = useId();
  const inputId = useId();
  const listId = useId();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(!open);
      }
      if (e.key === "Escape" && open) setOpen(false);
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_SEARCH_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_SEARCH_EVENT, onOpen);
    };
  }, [open, setOpen]);

  useEffect(() => {
    if (open && !wasOpen.current) {
      triggerRef.current = document.activeElement;
      inputRef.current?.focus();
    } else if (!open && wasOpen.current) {
      setTerm("");
      setAnswer(null);
      setActive(0);
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement) trigger.focus();
    }
    wasOpen.current = open;
  }, [open]);

  // Tab focus trap, active only while open, as ConfirmAction's.
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
    const q = term.trim();
    if (!q) return;
    const id = setTimeout(async () => {
      try {
        const data = await apiFetch<SearchResponse>(`/research/search?q=${encodeURIComponent(q)}`);
        setAnswer({ term: q, hits: data.results, failed: false });
      } catch {
        setAnswer({ term: q, hits: [], failed: true });
      }
    }, 200);
    return () => clearTimeout(id);
  }, [term]);

  if (!open) return null;

  const q = term.trim();
  const current = answer !== null && answer.term === q ? answer : null;
  const options: Option[] = [
    ...matchPages(q).map((p): Option => ({ key: `page:${p.href}`, group: "Pages", href: p.href, title: p.label, sub: p.hint, etf: false })),
    ...(current?.hits ?? []).map((h): Option => ({
      key: `ticker:${h.symbol}`,
      group: "Tickers",
      href: `/stock/${h.symbol}`,
      title: h.symbol,
      sub: h.name,
      etf: h.is_etf,
    })),
  ];
  const activeIndex = options.length === 0 ? -1 : Math.min(active, options.length - 1);
  const optionId = (i: number) => `${listId}-${i}`;

  function go(o: Option) {
    setOpen(false);
    router.push(o.href);
  }

  function onInputKey(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (options.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((activeIndex + 1) % options.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((activeIndex - 1 + options.length) % options.length);
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      go(options[activeIndex]!);
    }
  }

  let status: string | null = null;
  if (!q) status = "Type a ticker, a company or a page.";
  else if (current?.failed) status = "Tickers could not be searched right now.";
  else if (current && options.length === 0) status = `No ticker or page matches "${q}".`;
  else if (!current && options.length === 0) status = "Searching tickers.";

  const groups = (["Pages", "Tickers"] as const)
    .map((g) => ({ g, rows: options.map((o, i) => ({ o, i })).filter((x) => x.o.group === g) }))
    .filter((x) => x.rows.length > 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-scrim px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
      data-testid="search-scrim"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-xl rounded-[18px] bg-surface p-2"
      >
        <h2 id={titleId} className="sr-only">
          Search the console
        </h2>
        <div className="flex items-center gap-2 px-2">
          <Search aria-hidden="true" size={18} className="shrink-0 text-muted" />
          <label htmlFor={inputId} className="sr-only">
            Search a ticker, company or page
          </label>
          <input
            id={inputId}
            ref={inputRef}
            value={term}
            onChange={(e) => {
              setTerm(e.target.value);
              setActive(0);
            }}
            onKeyDown={onInputKey}
            placeholder="Search a ticker, company or page"
            role="combobox"
            aria-expanded={options.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
            autoComplete="off"
            spellCheck={false}
            className="min-h-11 w-full rounded-lg bg-transparent px-1 text-base text-content placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-focus"
          />
          <Button variant="quiet" className="shrink-0 md:hidden" onClick={() => setOpen(false)}>
            Close
          </Button>
        </div>
        <div className="border-t border-border">
          <div id={listId} role="listbox" aria-label="Results" className="max-h-[60vh] overflow-y-auto py-1">
            {groups.map(({ g, rows }) => (
              <div key={g} role="group" aria-labelledby={`${listId}-${g}`}>
                <div id={`${listId}-${g}`} className="px-3 pb-1 pt-2 text-xs font-semibold tracking-[0.04em] text-muted">
                  {g}
                </div>
                {rows.map(({ o, i }) => (
                  <div
                    key={o.key}
                    id={optionId(i)}
                    role="option"
                    aria-selected={i === activeIndex}
                    onMouseMove={() => setActive(i)}
                    onClick={() => go(o)}
                    className={clsx(
                      "flex min-h-11 cursor-pointer items-center gap-3 rounded-xl px-3 md:min-h-10",
                      i === activeIndex && "bg-sunk",
                    )}
                  >
                    <span className={clsx("shrink-0 font-semibold", o.group === "Tickers" && "tabular")}>{o.title}</span>
                    <span className="min-w-0 flex-1 truncate text-sm text-muted">{o.sub}</span>
                    {o.etf && <StatusWord>ETF</StatusWord>}
                  </div>
                ))}
              </div>
            ))}
          </div>
          {/* Always mounted, so a screen reader hears each change of the line. */}
          <p role="status" className={clsx("px-3 text-sm text-muted", status && "py-2")}>
            {status}
          </p>
          <p className="hidden px-3 pb-1 pt-2 text-xs text-muted md:block">
            Arrow keys to move, Enter to open, Esc to close
          </p>
        </div>
      </div>
    </div>
  );
}
