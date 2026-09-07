"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, apiFetch } from "@/lib/api";
import {
  submitUniverseCommand,
  useCommandStatus,
  type CommandStatus,
} from "@/lib/commands";
import { ConfirmAction } from "@/components/options/ConfirmAction";
import { CommandReceipt } from "@/components/options/CommandReceipt";

type Hit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
type SearchResponse = { as_of: string; query: string; results: Hit[] };

/**
 * The add control for an overridable universe list (M7 Task 7.5), rendered
 * once per overridable section (`would_own` or `watchlist`), below its
 * entries.
 *
 * A typeahead over the existing research symbol directory
 * (`GET /research/search`), adapting `CommandPalette`'s 200ms-debounced
 * search into an inline input plus dropdown rather than a full-screen
 * Cmd+K modal - a typo cannot become a `404` because the operator only ever
 * picks a real hit, never types a raw ticker straight into the write route.
 *
 * Adding to `would_own` opens a confirmation stating plainly that the system
 * may sell cash-secured puts on the symbol and may therefore be assigned its
 * shares - the real consequence, per spec §9.3 ("anything that can reach an
 * order confirms before the intent is created"). Adding to `watchlist` is a
 * reporting list only and fires immediately, no dialog.
 *
 * Universe write routes never return `needs_confirmation: true`, so there is
 * no live-mode second-confirmation step to build here (unlike `HaltControl`/
 * `AssessedRow`).
 */
export function AddSymbol({
  listName,
  drainHealthy = true,
}: {
  listName: "would_own" | "watchlist";
  drainHealthy?: boolean;
}) {
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [pendingHit, setPendingHit] = useState<Hit | null>(null);
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const qc = useQueryClient();

  // Poll every 2s while pending; stop once terminal (lib/commands.ts).
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  useEffect(() => {
    if (current && current.status !== "pending") {
      qc.invalidateQueries({ queryKey: ["universe"] });
    }
  }, [current, qc]);

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

  const inFlight = submitting || (current != null && current.status === "pending");

  async function fire(symbol: string) {
    setError(null);
    setSubmitting(true);
    try {
      const resp = await submitUniverseCommand("add", listName, symbol);
      setCommand(resp);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setSubmitting(false);
    }
  }

  function pick(hit: Hit) {
    setTerm("");
    setHits([]);
    if (listName === "would_own") {
      // Anything that can reach an order confirms first (spec §9.3): a
      // would_own addition can lead to a cash-secured put being sold.
      setPendingHit(hit);
    } else {
      // watchlist is a reporting list only - it never reaches an order, so
      // it fires immediately with no dialog.
      void fire(hit.symbol);
    }
  }

  async function onConfirm() {
    const hit = pendingHit;
    setPendingHit(null);
    if (hit === null) return;
    await fire(hit.symbol);
  }

  return (
    <div data-testid={`add-symbol-${listName}`}>
      <input
        value={term}
        disabled={inFlight}
        onChange={(e) => setTerm(e.target.value)}
        placeholder="Add a symbol"
        aria-label={`Add a symbol to ${listName}`}
        autoComplete="off"
        className="w-full max-w-xs rounded-sm border border-border bg-background px-2 py-1 font-mono text-sm text-content outline-none placeholder:text-muted focus-visible:border-focus disabled:opacity-50"
      />
      {hits.length > 0 && (
        <ul
          className="mt-1 max-w-xs rounded-sm border border-border bg-surface"
          data-testid={`add-symbol-hits-${listName}`}
        >
          {hits.map((h) => (
            <li key={h.symbol}>
              <button
                type="button"
                onClick={() => pick(h)}
                className="flex w-full items-baseline gap-3 px-2 py-1 text-left text-sm hover:bg-elevated focus-visible:bg-elevated"
              >
                <span className="tabular font-mono text-content">{h.symbol}</span>
                <span className="truncate text-xs text-muted">{h.name}</span>
                {h.is_etf && <span className="ml-auto text-[11px] text-muted">ETF</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {term.trim() && hits.length === 0 && (
        <p className="mt-1 text-xs text-muted">No match</p>
      )}

      {error && (
        <p
          className="mt-1 text-xs text-loss"
          role="alert"
          data-testid={`add-symbol-error-${listName}`}
        >
          {error}
        </p>
      )}

      {current && <CommandReceipt command={current} order={null} drainHealthy={drainHealthy} />}

      {pendingHit && (
        <ConfirmAction
          title={`Add ${pendingHit.symbol} to would own`}
          summary={
            <span>
              Adding {pendingHit.symbol} to the would-own list means the system may sell
              cash-secured puts on {pendingHit.symbol}. If a put is assigned, you would be
              assigned {pendingHit.symbol} shares.
            </span>
          }
          confirmLabel="Add symbol"
          onConfirm={onConfirm}
          onCancel={() => setPendingHit(null)}
        />
      )}
    </div>
  );
}

function describeError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) {
      return "You do not have permission to do this. Command not created.";
    }
    if (e.status === 404) {
      return "That symbol is not recognized. Command not created.";
    }
  }
  return "The command could not be created. Nothing was sent.";
}
