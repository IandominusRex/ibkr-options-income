"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch, ApiError } from "@/lib/api";
import { EmptyState } from "@/components/options/EmptyState";
import { Money } from "@/components/portfolio/Money";
import { BreakdownTable } from "./BreakdownTable";
import type { PnlLegData, PnlSummaryResponse } from "./types";

/**
 * The summary: headline figures, the by-strategy and by-symbol breakdowns,
 * and best/worst legs with links into the ledger.
 *
 * A `422 mixed_book` is a *choice*, not an error: the operator has both paper
 * and live trades and must pick one book before a total means anything. The
 * panel renders a labelled group of book buttons and an explanation in plain
 * words — never alert chrome, never a wrong number.
 *
 * `win_rate: null` renders `n/a`, not `0%`; `commissions_complete: false`
 * renders the gross qualifier on the headline realised figure (the same
 * qualifier Money renders, driven by the same flag).
 */
export function SummaryPanel({ book, onBookChange, onSelectLeg }: {
  book: string;
  onBookChange?: (next: string) => void;
  /** Jump to this leg in the ledger tab (`PnlShell` switches tab + filters by symbol). */
  onSelectLeg?: (leg: PnlLegData) => void;
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["pnl", "summary", book],
    queryFn: () =>
      apiFetch<PnlSummaryResponse>(`/pnl/summary?book=${book}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
    retry: false,
  });

  if (error instanceof ApiError && error.status === 422) {
    // The backend refused a mixed-book total. Render the choice in plain
    // words with a book selector — this is a normal situation, not a failure.
    return (
      <div className="space-y-3" data-testid="summary-panel">
        <p className="text-sm text-content">
          This summary would total both the paper and the live book. A total across
          both books is not a number that means anything — pick one.
        </p>
        <fieldset className="flex flex-wrap gap-2" role="group" aria-label="book">
          {["paper", "live"].map((b) => (
            <button
              key={b}
              type="button"
              onClick={() => onBookChange?.(b)}
              aria-pressed={book === b}
              className={
                "rounded border px-3 py-1 text-xs " +
                (book === b
                  ? "border-focus bg-elevated text-content"
                  : "border-border bg-surface text-muted hover:text-content")
              }
            >
              {b} book
            </button>
          ))}
        </fieldset>
      </div>
    );
  }

  if (isError) {
    return <p className="text-sm text-muted">Could not load the summary.</p>;
  }
  if (isLoading || !data) {
    return <p className="text-sm text-muted">Loading the summary</p>;
  }

  const s = data.summary;

  if (s.n_closed === 0 && s.n_open === 0) {
    return (
      <div className="space-y-3" data-testid="summary-panel">
        <EmptyState text={`No closed trades in the ${book} book yet.`} />
      </div>
    );
  }

  return (
    <div className="space-y-5" data-testid="summary-panel">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5">
        <Headline label="Realized total">
          <Money value={s.realized_total} kind="realized" signed complete={s.commissions_complete} />
        </Headline>
        <Headline label="Unrealized total">
          <Money value={s.unrealized_total} kind="unrealized" signed />
        </Headline>
        <Headline label="Open">
          <span className="tabular text-content">{s.n_open}</span>
        </Headline>
        <Headline label="Closed">
          <span className="tabular text-content">{s.n_closed}</span>
        </Headline>
        <Headline label="Win rate">
          {s.win_rate == null ? (
            <span className="tabular hatch text-unknown">n/a</span>
          ) : (
            <span className="tabular text-content">{Math.round(s.win_rate * 100)}%</span>
          )}
        </Headline>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <BreakdownTable buckets={s.by_strategy ?? []} label="By strategy" />
        <BreakdownTable buckets={s.by_symbol ?? []} label="By symbol" />
      </div>

      {(s.best || s.worst) && (
        <div className="space-y-2">
          <h3 className="text-xs uppercase tracking-wide text-muted">Best and worst closed legs</h3>
          <ul className="space-y-1 text-xs">
            {s.best && <BestWorstRow leg={s.best} which="best" onSelect={onSelectLeg} />}
            {s.worst && <BestWorstRow leg={s.worst} which="worst" onSelect={onSelectLeg} />}
          </ul>
        </div>
      )}
    </div>
  );
}

function Headline({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </div>
  );
}

function BestWorstRow({
  leg,
  which,
  onSelect,
}: {
  leg: PnlLegData;
  which: string;
  onSelect?: (leg: PnlLegData) => void;
}) {
  const contract = `${leg.underlying} ${leg.right} ${leg.strike?.toFixed(2)}`;
  return (
    <li className="flex flex-wrap items-center justify-between gap-4">
      <span className="text-muted">
        {which === "best" ? "Best" : "Worst"}:{" "}
        {onSelect ? (
          <button
            type="button"
            onClick={() => onSelect(leg)}
            aria-label={`View ${contract} in the ledger`}
            className="font-mono text-content underline decoration-dotted underline-offset-2 hover:text-focus"
          >
            {contract}
          </button>
        ) : (
          <span className="font-mono text-content">{contract}</span>
        )}
      </span>
      <span className="flex items-center gap-3">
        <Money value={leg.net_pnl} kind="realized" signed complete={leg.commissions_complete} />
        <span className="font-mono text-muted">{leg.candidate_id}</span>
      </span>
    </li>
  );
}