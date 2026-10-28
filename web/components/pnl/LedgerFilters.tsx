"use client";

import clsx from "clsx";
import { useState } from "react";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";

type BookFilter = "all" | "paper" | "live";

/**
 * The filter strip above the ledger. Filters drive the query string, not
 * client-side array filtering, so the CSV export link and the JSON table
 * request the same rows from the backend under the same params — a client-side
 * `.filter()` would let the two drift.
 *
 * The parent owns the query string (the page composes it into the totals, the
 * curve, the legs and the export href); this component reports the next filter
 * set. `filters` is the page's own live filter draft — NOT the backend's echoed
 * response (`LedgerTable`'s separate filter-echo reads that instead), because
 * seeding local state from a request echo would lag one round trip behind. It
 * seeds local state only via `useState`'s lazy initializer, read once — this
 * component stays fast to type in even while a request is in flight. The one
 * case that needs the inputs to change without a keystroke of their own — the
 * summary's "view in ledger" link changing `symbol` externally — works by the
 * parent remounting this component with a fresh `key` instead of a live-sync
 * effect, which would risk clobbering a value the user is mid-typing when a
 * slightly-stale response lands.
 */
export function LedgerFilters({
  filters,
  onChange,
}: {
  filters: Record<string, string> | undefined;
  onChange: (next: Record<string, string>) => void;
}) {
  const [symbol, setSymbol] = useState(filters?.symbol ?? "");
  const [book, setBook] = useState<BookFilter>((filters?.book as BookFilter) || "all");
  const [outcome, setOutcome] = useState(filters?.outcome ?? "");
  const [since, setSince] = useState(filters?.since ?? "");
  const [until, setUntil] = useState(filters?.until ?? "");

  function emit(next: Record<string, string>) {
    onChange(next);
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="ledger-filters">
      <div className="grid gap-1">
        <label htmlFor="ledger-symbol-filter" className={FIELD_LABEL}>
          Symbol
        </label>
        <input
          id="ledger-symbol-filter"
          type="text"
          value={symbol}
          onChange={(e) => {
            setSymbol(e.target.value);
            emit({ book, outcome, since, until, symbol: e.target.value.toUpperCase() });
          }}
          placeholder="NVDA"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          className={clsx(FIELD, "w-full")}
        />
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-book-filter" className={FIELD_LABEL}>
          Book
        </label>
        <select
          id="ledger-book-filter"
          value={book}
          onChange={(e) => {
            const nextBook = e.target.value as BookFilter;
            setBook(nextBook);
            emit({ book: nextBook, outcome, since, until, symbol });
          }}
          className={clsx(FIELD, "w-full")}
        >
          <option value="all">all</option>
          <option value="paper">paper</option>
          <option value="live">live</option>
        </select>
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-outcome-filter" className={FIELD_LABEL}>
          Outcome
        </label>
        <select
          id="ledger-outcome-filter"
          value={outcome}
          onChange={(e) => {
            setOutcome(e.target.value);
            emit({ book, outcome: e.target.value, since, until, symbol });
          }}
          className={clsx(FIELD, "w-full")}
        >
          <option value="">all</option>
          <option value="still_open">still open</option>
          <option value="expired_worthless">expired worthless</option>
          <option value="assigned">assigned</option>
          <option value="closed_early">closed early</option>
        </select>
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-since-filter" className={FIELD_LABEL}>
          Since
        </label>
        <input
          id="ledger-since-filter"
          type="date"
          value={since}
          onChange={(e) => {
            setSince(e.target.value);
            emit({ book, outcome, since: e.target.value, until, symbol });
          }}
          className={clsx(FIELD, "w-full")}
        />
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-until-filter" className={FIELD_LABEL}>
          Until
        </label>
        <input
          id="ledger-until-filter"
          type="date"
          value={until}
          onChange={(e) => {
            setUntil(e.target.value);
            emit({ book, outcome, since, until: e.target.value, symbol });
          }}
          className={clsx(FIELD, "w-full")}
        />
      </div>
    </div>
  );
}
