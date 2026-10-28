"use client";

import clsx from "clsx";
import { useState } from "react";
import { DatePicker } from "@/components/ui/DatePicker";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { Select } from "@/components/ui/Select";

type BookFilter = "all" | "paper" | "live";

const BOOKS = [
  { value: "all", label: "All" },
  { value: "paper", label: "Paper" },
  { value: "live", label: "Live" },
];

const OUTCOMES = [
  { value: "", label: "All" },
  { value: "still_open", label: "Still open" },
  { value: "expired_worthless", label: "Expired worthless" },
  { value: "assigned", label: "Assigned" },
  { value: "closed_early", label: "Closed early" },
];

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
        <Select
          id="ledger-book-filter"
          value={book}
          onChange={(v) => {
            const nextBook = v as BookFilter;
            setBook(nextBook);
            emit({ book: nextBook, outcome, since, until, symbol });
          }}
          options={BOOKS}
        />
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-outcome-filter" className={FIELD_LABEL}>
          Outcome
        </label>
        <Select
          id="ledger-outcome-filter"
          value={outcome}
          onChange={(v) => {
            setOutcome(v);
            emit({ book, outcome: v, since, until, symbol });
          }}
          options={OUTCOMES}
        />
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-since-filter" className={FIELD_LABEL}>
          Since
        </label>
        <DatePicker
          id="ledger-since-filter"
          value={since}
          max={until || undefined}
          onChange={(v) => {
            setSince(v);
            emit({ book, outcome, since: v, until, symbol });
          }}
        />
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-until-filter" className={FIELD_LABEL}>
          Until
        </label>
        <DatePicker
          id="ledger-until-filter"
          value={until}
          min={since || undefined}
          onChange={(v) => {
            setUntil(v);
            emit({ book, outcome, since, until: v, symbol });
          }}
        />
      </div>
    </div>
  );
}
