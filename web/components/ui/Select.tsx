"use client";

import clsx from "clsx";
import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { FIELD } from "./field";

export type SelectOption = { value: string; label: string };

/**
 * A select drawn in the console's own face (web/DESIGN.md Components → Field): the trigger is the
 * `field`, the list is a white panel on a control edge (tonal, no shadow), the chosen option
 * carries a check and a heavier weight, the one under the pointer or the arrow keys a pressed-sage
 * fill. Keyboard follows the WAI-ARIA select-only combobox: arrows, Home, End, type-ahead, Enter
 * or Space to choose, Escape to close and give focus back to the trigger. The list opens upward
 * when there is no room below. Pair it with a `<label htmlFor={id}>`, as a native select.
 */
export function Select({
  id,
  value,
  onChange,
  options,
  className,
  disabled = false,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
}) {
  const autoId = useId();
  const triggerId = id ?? autoId;
  const listId = `${triggerId}-list`;
  const [open, setOpen] = useState(false);
  const [openUp, setOpenUp] = useState(false);
  const [active, setActive] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const typed = useRef<{ text: string; at: number }>({ text: "", at: 0 });

  const selected = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );
  const current = options.find((o) => o.value === value);

  function show() {
    if (disabled || options.length === 0) return;
    const box = triggerRef.current?.getBoundingClientRect();
    // The list is at most 18rem tall: flip it up when the space below is short and above is longer.
    if (box) setOpenUp(window.innerHeight - box.bottom < 300 && box.top > window.innerHeight - box.bottom);
    setActive(selected);
    setOpen(true);
  }

  function close(refocus: boolean) {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }

  function choose(i: number) {
    const o = options[i];
    if (o) onChange(o.value);
    close(true);
  }

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  useEffect(() => {
    if (open) listRef.current?.children[active]?.scrollIntoView?.({ block: "nearest" });
  }, [open, active]);

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    const last = options.length - 1;
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        show();
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActive((a) => Math.min(last, a + 1));
        return;
      case "ArrowUp":
        e.preventDefault();
        setActive((a) => Math.max(0, a - 1));
        return;
      case "Home":
        e.preventDefault();
        setActive(0);
        return;
      case "End":
        e.preventDefault();
        setActive(last);
        return;
      case "Enter":
      case " ":
        e.preventDefault();
        choose(active);
        return;
      case "Escape":
        e.preventDefault();
        close(true);
        return;
      case "Tab":
        setOpen(false);
        return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // Type-ahead: letters typed within a second build one prefix.
      const now = Date.now();
      const text = (now - typed.current.at < 1000 ? typed.current.text : "") + e.key.toLowerCase();
      typed.current = { text, at: now };
      const from = text.length === 1 ? active + 1 : active;
      const hit = [...options.slice(from), ...options.slice(0, from)].find((o) => o.label.toLowerCase().startsWith(text));
      if (hit) setActive(options.indexOf(hit));
    }
  }

  return (
    <div ref={wrapRef} className={clsx("relative", className)}>
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => (open ? close(false) : show())}
        onKeyDown={onKeyDown}
        className={clsx(
          FIELD,
          "flex w-full items-center justify-between gap-2 text-left enabled:hover:bg-sunk disabled:cursor-default disabled:text-muted",
        )}
      >
        <span className="min-w-0 truncate">{current?.label ?? ""}</span>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className={clsx(
            "shrink-0 text-muted transition-transform duration-[180ms] ease-out motion-reduce:transition-none",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          aria-labelledby={triggerId}
          className={clsx(
            "absolute left-0 z-30 max-h-72 min-w-full overflow-auto rounded-xl border border-control bg-surface p-1.5",
            openUp ? "bottom-full mb-1.5" : "top-full mt-1.5",
          )}
        >
          {options.map((o, i) => {
            const on = i === selected;
            return (
              <li
                key={o.value}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={on}
                // Pointer down would pull focus off the trigger before the click lands.
                onPointerDown={(e) => e.preventDefault()}
                onPointerMove={() => i !== active && setActive(i)}
                onClick={() => choose(i)}
                className={clsx(
                  "flex min-h-11 cursor-default items-center justify-between gap-4 rounded-lg px-3 text-[0.9375rem] md:min-h-9",
                  on ? "font-semibold" : "font-normal",
                  i === active && "bg-sunk",
                )}
              >
                <span className="whitespace-nowrap">{o.label}</span>
                {on && <Check size={16} strokeWidth={2.5} aria-hidden="true" className="shrink-0" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
