"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * The confirmation dialog (P2 spec §9.3).
 *
 * Anything that can reach an order confirms here before the intent is created.
 * The summary renders the exact contract and contract count — never summarised
 * away. With `requireTypedWord`, the confirm control stays disabled until the
 * word matches exactly, case-sensitive (used by `halt` in M6). Escape and the
 * cancel control both call `onCancel`. Focus is trapped while open and returns
 * to the trigger on close. The entry transition is disabled under
 * prefers-reduced-motion.
 */
export type ConfirmActionProps = {
  title: string;
  summary: ReactNode;
  confirmLabel: string;
  requireTypedWord?: string;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmAction({
  title,
  summary,
  confirmLabel,
  requireTypedWord,
  onConfirm,
  onCancel,
}: ConfirmActionProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<Element | null>(null);
  const [typed, setTyped] = useState("");
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  const headingId = useId();

  useEffect(() => {
    // Remember the trigger so focus returns to it on close.
    triggerRef.current = document.activeElement;
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    setPrefersReducedMotion(mql.matches);
    const onMotionChange = (e: MediaQueryListEvent) => setPrefersReducedMotion(e.matches);
    mql.addEventListener("change", onMotionChange);
    return () => mql.removeEventListener("change", onMotionChange);
  }, []);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      // Focus trap: cycle within the dialog's focusable controls.
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
  }, [onCancel]);

  useEffect(() => {
    // Return focus to the trigger on unmount (close).
    return () => {
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement) trigger.focus();
    };
  }, []);

  const wordMatches =
    requireTypedWord === undefined ? true : typed === requireTypedWord;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={headingId}
      data-testid="confirm-dialog"
      className={
        "fixed inset-0 z-50 flex items-start justify-center bg-scrim px-4 pt-[15vh] " +
        (prefersReducedMotion ? "" : "animate-receipt-entry")
      }
    >
      <div
        className="w-full max-w-xl rounded-md border border-border bg-surface p-4"
        data-testid="confirm-dialog-panel"
      >
        <h2 id={headingId} className="text-lg text-content">
          {title}
        </h2>
        <div className="mt-3 text-sm text-content" data-testid="confirm-summary">
          {summary}
        </div>
        {requireTypedWord !== undefined && (
          <div className="mt-4">
            <label
              htmlFor={`${headingId}-typed`}
              className="mb-1 block text-xs text-muted"
            >
              Type <span className="font-mono text-content">{requireTypedWord}</span> to
              confirm
            </label>
            <input
              id={`${headingId}-typed`}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              className="w-full rounded-sm border border-border bg-background px-2 py-1 font-mono text-sm text-content outline-none focus-visible:border-focus"
            />
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content hover:bg-elevated focus-visible:ring-focus"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!wordMatches}
            onClick={onConfirm}
            className="rounded-sm border border-focus bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}