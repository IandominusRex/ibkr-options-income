"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { apiFetch } from "@/lib/api";
import type { SystemRow } from "./SystemStatusCard";

type LogLevel = "warn" | "info";

type SystemLogResponse = {
  as_of: string;
  name: string;
  level: LogLevel;
  lines: string[];
  file_exists: boolean;
};

export function SystemLogPanel({ row, onClose }: { row: SystemRow; onClose: () => void }) {
  const [level, setLevel] = useState<LogLevel>("warn");
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<Element | null>(null);
  const headingId = useId();

  const { data, isFetching, isError, refetch } = useQuery({
    queryKey: ["system", "log", row.log_key, level],
    queryFn: () => apiFetch<SystemLogResponse>(`/system/${row.log_key}/log?level=${level}`),
    enabled: row.log_key !== null,
  });

  useEffect(() => {
    triggerRef.current = document.activeElement;
    closeRef.current?.focus();
    return () => {
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement) trigger.focus();
    };
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusables = panel.querySelectorAll<HTMLElement>(
        "button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
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
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-scrim" aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        data-testid="system-log-panel"
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-surface p-4"
      >
        <div className="flex items-center justify-between gap-2">
          <h2 id={headingId} className="text-sm text-content">
            {row.label}
          </h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="rounded-sm border border-border bg-background px-2 py-1 text-xs text-content hover:bg-elevated focus-visible:ring-focus"
          >
            Close
          </button>
        </div>
        <p className="mt-1 text-xs text-muted">{row.detail}</p>

        <div className="mt-3 flex items-center gap-2">
          <div className="flex gap-1" role="group" aria-label="Log level">
            {(["warn", "info"] as const).map((lvl) => (
              <button
                key={lvl}
                type="button"
                aria-pressed={level === lvl}
                onClick={() => setLevel(lvl)}
                className={clsx(
                  "rounded-sm border px-2 py-1 text-xs",
                  level === lvl
                    ? "border-focus text-content"
                    : "border-border text-muted hover:bg-elevated",
                )}
              >
                {lvl === "warn" ? "Warnings+" : "Info+"}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="rounded-sm border border-border bg-background px-2 py-1 text-xs text-content enabled:hover:bg-elevated disabled:opacity-50"
          >
            Refresh
          </button>
        </div>

        <div className="mt-3 flex-1 overflow-y-auto rounded-sm border border-border bg-background p-2">
          {isError ? (
            <p className="text-xs text-muted">Could not load the log</p>
          ) : data === undefined ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : !data.file_exists ? (
            <p className="text-xs text-muted">No log file yet</p>
          ) : data.lines.length === 0 ? (
            <p className="text-xs text-muted">No matching lines at this level</p>
          ) : (
            <pre className="whitespace-pre-wrap font-mono text-xs text-content">
              {data.lines.join("\n")}
            </pre>
          )}
        </div>
      </div>
    </>
  );
}
