"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import type { ShortListResponse } from "@/components/options/types";
import { FreshnessLabel } from "@/components/portfolio/FreshnessLabel";
import type { PositionsResponse } from "@/components/portfolio/types";
import { Card } from "@/components/ui/Card";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { formatStubValue } from "@/components/ui/Stub";
import { PositionRowItem } from "@/features/home/PositionRowItem";
import { FRESH_FOR_MINUTES } from "@/features/home/positions";
import type { SpreadPositionsResponse } from "@/features/home/types";
import { NameFlags } from "@/features/market/NameFlags";
import { todayInNewYork } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell, isStale } from "@/lib/money";
import { shortDate } from "./format";
import {
  EMPTY,
  FILTERS,
  FILTER_LABEL,
  type DetailPart,
  type NameCard,
  type NamePrice,
  type PositionsFilter,
  buildNameCards,
  countByFilter,
  nameFigures,
  nameSummary,
  narrow,
  narrowRows,
  rowsPnl,
  spreadRows,
} from "./positions";

function Detail({ parts }: { parts: DetailPart[] }): ReactNode {
  return (
    <>
      {parts.map((p, i) => (
        <span key={p.label}>
          {i > 0 && " · "}
          {p.label} {p.value === null ? <span className="hatch text-unknown">{UNKNOWN}</span> : p.value}
        </span>
      ))}
    </>
  );
}

/** The price at the card's top right, and where it came from: "Close Oct 27" for a name held only through options. */
function PriceBlock({ price }: { price: NamePrice | null }) {
  if (price === null) {
    return (
      <div data-testid="name-price" className="text-right">
        <span className="hatch tabular text-lg font-extrabold text-unknown">{UNKNOWN}</span>
        <div className="text-[0.8125rem] text-muted">price</div>
      </div>
    );
  }
  return (
    <div data-testid="name-price" className="text-right">
      <div className="tabular text-xl font-extrabold leading-tight tracking-[-0.01em]">{formatMoneyCell(price.value)}</div>
      <div className="text-[0.8125rem] text-muted">
        {price.basis === "close" && price.date ? `Close ${shortDate(price.date).replace(/, \d{4}$/, "")}` : "Last price"}
      </div>
    </div>
  );
}

function NameCardView({ card }: { card: NameCard }) {
  const pnl = rowsPnl(card.rows);
  const titleId = `name-${card.underlying}`;
  const figures = nameFigures(card);
  return (
    <Card as="article" aria-labelledby={titleId}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={titleId} className="inline text-[1.0625rem] font-bold">
            {card.underlying}
          </h3>
          <NameFlags symbol={card.underlying} />
          <p className="tabular mt-0.5 text-[0.8125rem] text-muted">{nameSummary(card)}</p>
        </div>
        <PriceBlock price={card.price} />
      </div>
      <div data-testid="name-pnl" className="mt-3 flex flex-wrap items-baseline gap-x-2">
        <span
          className={clsx(
            "tabular text-[1.625rem] font-extrabold leading-none tracking-[-0.02em]",
            pnl === null && "hatch text-unknown",
            pnl !== null && pnl < 0 && "text-loss",
            pnl !== null && pnl > 0 && "text-gain",
          )}
        >
          {pnl === null ? UNKNOWN : formatStubValue(pnl, "signed-money")}
        </span>
        <span className="text-[0.8125rem] text-muted">open P&amp;L</span>
      </div>
      {figures.length > 0 && (
        <dl className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(6.5rem,1fr))] gap-x-4 gap-y-2.5">
          {figures.map((f) => (
            <div key={f.label} className="min-w-0">
              <dt className="text-xs font-semibold tracking-[0.04em] text-muted">{f.label}</dt>
              <dd className={clsx("tabular text-sm font-semibold", f.value === null && "hatch w-fit text-unknown")}>
                {f.value ?? UNKNOWN}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <ul className="mt-3 border-t-2 border-dashed border-perforation pt-1">
        {card.rows.map((r) => (
          <PositionRowItem
            key={r.key}
            row={r}
            flags={false}
            detail={card.details[r.key] ? <Detail parts={card.details[r.key]} /> : undefined}
          />
        ))}
      </ul>
    </Card>
  );
}

/**
 * Positions, name by name: Home's rows under each ticker with the figures a register needs. The
 * data is the three requests Home's card makes, under the same query keys, so a visit to both asks
 * once. A name's total is the sum of what its rows show, or n/a; an unreadable spreads book is
 * said, never shown as none.
 */
export function PositionsView() {
  const [filter, setFilter] = useState<PositionsFilter>("all");
  const [query, setQuery] = useState("");
  const searchId = useId();

  const positions = useQuery({
    queryKey: ["portfolio", "positions"],
    queryFn: () => apiFetch<PositionsResponse>("/portfolio/positions"),
    refetchInterval: 60_000,
  });
  const spreads = useQuery({
    queryKey: ["spreads", "positions", "open"],
    queryFn: () => apiFetch<SpreadPositionsResponse>("/spreads/positions?status=open"),
    refetchInterval: 60_000,
  });
  const shorts = useQuery({
    queryKey: ["options", "shorts"],
    queryFn: () => apiFetch<ShortListResponse>("/options/shorts"),
    refetchInterval: 60_000,
  });

  const today = todayInNewYork();
  const alerted = new Set(
    (shorts.data?.shorts ?? []).filter((s) => s.alerts.length > 0).map((s) => s.position_symbol),
  );
  // Unknown is never none: an unreadable spreads book is not an empty one.
  const spreadsKnown = spreads.data?.available === true;
  const spreadsOut = spreads.isError || spreads.data?.available === false;
  const allCards = positions.data ? buildNameCards(positions.data.groups, today, alerted) : [];
  const allSpreads = spreadsKnown ? spreadRows(spreads.data!.positions, today, spreads.data!.underlying) : [];
  const cards = narrow(allCards, filter, query);
  const spreadList = narrowRows(allSpreads, filter, query);
  const counts = countByFilter(allCards, allSpreads, query);
  const options = FILTERS.map((f) => ({
    value: f,
    label: FILTER_LABEL[f],
    count: !positions.data || (f === "spread" && !spreadsKnown) ? null : counts[f],
  }));
  const searching = query.trim() !== "";

  let message: string | null = null;
  if (positions.isError && !positions.data) message = "Positions unavailable right now.";
  else if (positions.data && cards.length === 0 && spreadList.length === 0) {
    if (searching) message = `No positions match "${query.trim()}".`;
    else if (filter === "spread" && spreadsOut) message = "Credit spreads are unavailable right now.";
    else if (filter === "spread" && spreads.isPending) message = "Loading credit spreads.";
    else if (positions.data.source === "none" && filter !== "spread")
      message = "No portfolio snapshot has been captured yet.";
    else message = EMPTY[filter];
  }
  const loading = !positions.data && !positions.isError;
  const delayed =
    positions.data !== undefined &&
    positions.data.source !== "none" &&
    (positions.data.degraded || isStale(positions.data.as_of, FRESH_FOR_MINUTES));

  return (
    <div className="grid gap-3">
      <form role="search" onSubmit={(e) => e.preventDefault()} className="relative">
        <label htmlFor={searchId} className="sr-only">
          Search positions
        </label>
        <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          id={searchId}
          type="text"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a ticker, like AMZN"
          // 16px: below that, iOS zooms the page when the field takes focus.
          className="min-h-11 w-full rounded-xl border border-control bg-surface pl-9 pr-11 text-base placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        />
        {searching && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => setQuery("")}
            className="absolute right-0 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full text-muted hover:bg-sunk hover:text-content md:right-1 md:h-9 md:w-9"
          >
            <X size={16} aria-hidden="true" />
          </button>
        )}
      </form>
      <SegmentedControl label="Position type" appearance="chips" options={options} value={filter} onChange={setFilter} />
      {delayed && (
        <p className="flex flex-wrap items-center gap-2">
          <StatusWord tone="flag">Delayed</StatusWord>
          <FreshnessLabel asOf={positions.data!.as_of} freshForMinutes={FRESH_FOR_MINUTES} />
        </p>
      )}
      {loading ? (
        <div role="status" aria-busy="true" aria-label="Loading positions" className="space-y-3">
          <div className="h-24 rounded-[18px] bg-surface" />
          <div className="h-24 rounded-[18px] bg-surface" />
        </div>
      ) : message !== null ? (
        <p className="py-3 text-sm text-muted">{message}</p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {cards.map((c) => (
            <NameCardView key={c.underlying} card={c} />
          ))}
          {spreadList.length > 0 && (
            <Card as="article" aria-labelledby="name-spreads">
              <h3 id="name-spreads" className="text-[1.0625rem] font-bold">
                {spreads.data!.underlying} credit spreads
              </h3>
              <ul className="mt-1">
                {spreadList.map((r) => (
                  <PositionRowItem key={r.key} row={r} flags={false} />
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
      {filter === "all" && spreadsOut && positions.data && (
        <p className="border-t border-border pt-2.5 text-[0.8125rem] text-muted">
          Credit spreads are unavailable right now, so they are not listed.
        </p>
      )}
    </div>
  );
}
