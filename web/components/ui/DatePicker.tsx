"use client";

import clsx from "clsx";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { todayInNewYork } from "@/features/trades/time";
import { addDays, addMonths, longDay, monthRows, monthTitle, parseIso, shortDay, weekdayIndex } from "./dates";
import { FIELD } from "./field";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

/**
 * A day picker in the console's own face (web/DESIGN.md Components → Field), a drop-in for
 * `<input type="date">`: the value is `YYYY-MM-DD` or "" for no day, so a filter that is optional
 * stays optional. The trigger is the `field`; the panel is white on a control edge (tonal, no
 * shadow) with the month between two arrows, the days Monday-first as 40px circles (44px on a
 * phone), the chosen day an ink fill and today a ring. Keyboard follows the WAI-ARIA date picker
 * dialog: arrows move a day or a week, Home and End the week's ends, Page Up and Down a month
 * (with Shift a year), Enter or Space chooses, Escape closes and returns focus to the trigger.
 * `min` and `max` grey out the days outside them.
 */
export function DatePicker({
  id,
  value,
  onChange,
  min,
  max,
  placeholder = "Any day",
  className,
  "aria-label": ariaLabel,
  "data-role": dataRole,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  placeholder?: string;
  className?: string;
  "aria-label"?: string;
  /** Passed to the trigger, for a surface that must list every control it offers. */
  "data-role"?: string;
}) {
  const autoId = useId();
  const triggerId = id ?? autoId;
  const panelId = `${triggerId}-panel`;
  const today = todayInNewYork();
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const [openUp, setOpenUp] = useState(false);
  // The day the arrow keys are on, and with it the month shown.
  const [focus, setFocus] = useState(today);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  // Real focus follows the keys, but not a click on a month arrow: that keeps the arrow.
  const moveFocus = useRef(false);

  const chosen = parseIso(value) ? value : "";
  const allowed = (iso: string) => (min === undefined || iso >= min) && (max === undefined || iso <= max);
  const clamp = (iso: string) => (min !== undefined && iso < min ? min : max !== undefined && iso > max ? max : iso);

  function show() {
    const box = triggerRef.current?.getBoundingClientRect();
    if (box) {
      // The panel is 19.5rem wide and about 25rem tall: keep it on screen.
      setAlignRight(box.left + 312 > window.innerWidth - 16);
      setOpenUp(window.innerHeight - box.bottom < 420 && box.top > window.innerHeight - box.bottom);
    }
    setFocus(clamp(chosen || today));
    moveFocus.current = true;
    setOpen(true);
  }

  function close(refocus: boolean) {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }

  function pick(iso: string) {
    if (!allowed(iso)) return;
    onChange(iso);
    close(true);
  }

  // Move real focus to the day the keys are on, whenever the panel is open.
  useEffect(() => {
    if (open && moveFocus.current) {
      moveFocus.current = false;
      gridRef.current?.querySelector<HTMLButtonElement>('button[tabindex="0"]')?.focus();
    }
  }, [open, focus]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  function go(next: string) {
    setFocus(clamp(next));
  }

  function onGridKey(e: KeyboardEvent<HTMLDivElement>) {
    const steps: Record<string, string | undefined> = {
      ArrowLeft: addDays(focus, -1),
      ArrowRight: addDays(focus, 1),
      ArrowUp: addDays(focus, -7),
      ArrowDown: addDays(focus, 7),
      PageUp: addMonths(focus, e.shiftKey ? -12 : -1),
      PageDown: addMonths(focus, e.shiftKey ? 12 : 1),
    };
    const next = steps[e.key];
    if (next) {
      e.preventDefault();
      moveFocus.current = true;
      go(next);
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      moveFocus.current = true;
      const dayOfWeek = weekdayIndex(parseIso(focus)!);
      go(addDays(focus, e.key === "Home" ? -dayOfWeek : 6 - dayOfWeek));
    }
  }

  function onPanelKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(true);
    }
  }

  const f = parseIso(focus)!;
  const rows = monthRows(f.y, f.m);
  // An arrow stops where the month it leads to holds no allowed day.
  const first = `${String(f.y).padStart(4, "0")}-${String(f.m).padStart(2, "0")}-01`;
  const prevBlocked = min !== undefined && addDays(first, -1) < min;
  const nextBlocked = max !== undefined && addMonths(first, 1) > max;

  return (
    <div
      ref={wrapRef}
      className={clsx("relative", className)}
      onBlur={(e) => {
        // Tabbing out closes the panel; a click on its bare areas (no related target) does not.
        if (open && e.relatedTarget && !wrapRef.current?.contains(e.relatedTarget as Node)) setOpen(false);
      }}
    >
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={ariaLabel}
        data-role={dataRole}
        onClick={() => (open ? close(false) : show())}
        className={clsx(FIELD, "flex w-full items-center justify-between gap-2 text-left hover:bg-sunk")}
      >
        <span className={clsx("tabular min-w-0 truncate", chosen === "" && "text-muted")}>
          {chosen === "" ? placeholder : shortDay(chosen)}
        </span>
        <CalendarDays size={18} aria-hidden="true" className="shrink-0 text-muted" />
      </button>
      {open && (
        <div
          id={panelId}
          role="dialog"
          aria-label="Choose a day"
          onKeyDown={onPanelKey}
          className={clsx(
            "absolute z-30 w-[19.5rem] max-w-[calc(100vw-2rem)] rounded-xl border border-control bg-surface p-3",
            alignRight ? "right-0" : "left-0",
            openUp ? "bottom-full mb-1.5" : "top-full mt-1.5",
          )}
        >
          <div className="flex items-center justify-between gap-1">
            <button
              type="button"
              aria-label="Previous month"
              disabled={prevBlocked}
              onClick={() => go(addMonths(focus, -1))}
              className="grid h-11 w-11 place-items-center rounded-full text-content hover:bg-sunk disabled:text-muted disabled:hover:bg-transparent md:h-9 md:w-9"
            >
              <ChevronLeft size={18} strokeWidth={2.25} aria-hidden="true" />
            </button>
            <p aria-live="polite" className="text-[0.9375rem] font-bold">
              {monthTitle(f.y, f.m)}
            </p>
            <button
              type="button"
              aria-label="Next month"
              disabled={nextBlocked}
              onClick={() => go(addMonths(focus, 1))}
              className="grid h-11 w-11 place-items-center rounded-full text-content hover:bg-sunk disabled:text-muted disabled:hover:bg-transparent md:h-9 md:w-9"
            >
              <ChevronRight size={18} strokeWidth={2.25} aria-hidden="true" />
            </button>
          </div>
          <div ref={gridRef} role="grid" aria-label={monthTitle(f.y, f.m)} onKeyDown={onGridKey} className="mt-1">
            <div role="row" className="grid grid-cols-7">
              {WEEKDAYS.map((w) => (
                <span key={w} role="columnheader" className="grid h-8 place-items-center text-xs font-semibold tracking-[0.04em] text-muted">
                  {w}
                </span>
              ))}
            </div>
            {rows.map((row, r) => (
              <div key={r} role="row" className="grid grid-cols-7">
                {row.map((iso, c) => {
                  if (iso === null) return <span key={c} role="gridcell" className="h-11 md:h-10" />;
                  const on = iso === chosen;
                  const ok = allowed(iso);
                  return (
                    <span key={iso} role="gridcell" aria-selected={on} className="grid place-items-center">
                      <button
                        type="button"
                        tabIndex={iso === focus ? 0 : -1}
                        aria-label={longDay(iso)}
                        aria-pressed={on}
                        aria-current={iso === today ? "date" : undefined}
                        disabled={!ok}
                        onClick={() => pick(iso)}
                        className={clsx(
                          "tabular grid h-11 w-11 place-items-center rounded-full text-sm md:h-10 md:w-10",
                          on ? "bg-content font-bold text-background" : "font-medium enabled:hover:bg-sunk",
                          !on && iso === today && "ring-1 ring-inset ring-control",
                          !ok && "text-muted line-through",
                        )}
                      >
                        {Number(iso.slice(8))}
                      </button>
                    </span>
                  );
                })}
              </div>
            ))}
          </div>
          <div className="mt-2 flex items-center justify-between border-t border-border pt-2">
            <button
              type="button"
              disabled={!allowed(today)}
              onClick={() => pick(today)}
              className="min-h-11 rounded-full px-3 text-sm font-bold hover:bg-sunk disabled:text-muted disabled:hover:bg-transparent md:min-h-9"
            >
              Today
            </button>
            <button
              type="button"
              disabled={chosen === ""}
              onClick={() => {
                onChange("");
                close(true);
              }}
              className="min-h-11 rounded-full px-3 text-sm font-bold hover:bg-sunk disabled:text-muted disabled:hover:bg-transparent md:min-h-9"
            >
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
