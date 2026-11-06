"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { shortDate } from "@/features/portfolio/format";
import { Hatched } from "@/features/stock-value/parts";
import { apiFetch } from "@/lib/api";
import { formatMoneyCell } from "@/lib/money";

type SearchHit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
type SearchResponse = { as_of: string; query: string; results: SearchHit[] };

type WatchlistItem = {
  symbol: string;
  name: string;
  price: { value: number | null; source: string; as_of: string; stale: boolean } | null;
  change_pct: number | null;
  iv_rank: number | null;
  checks: { passed: number; evaluable: number; unknown: number };
  next_earnings: string | null;
};

type WatchlistResponse = { as_of: string; items: WatchlistItem[] };

/** "+1.50%": a price move is signed but never green or red, because it is not money (web/DESIGN.md Colors). */
function signedPct(v: number): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/**
 * "Your watchlist" on Research (web overhaul Part 6): the names the operator follows here, kept in
 * research.db so their quotes stay warm. It is not the scan's own watchlist (that one is on Universe and
 * changes through a command), and the card says so. Add is a typeahead over `GET /research/search`, so a
 * typo never reaches the write route; a pick adds at once (no order consequence, no dialog), and the
 * input is disabled while an add is in flight. Each row links to the stock page and has its own Remove,
 * disabled while that row's remove is in flight. Unknown is a hatched n/a; a failed read or write is a
 * sentence, never an empty list.
 */
export function WatchlistTable() {
  const qc = useQueryClient();
  const { data, isError } = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => apiFetch<WatchlistResponse>("/watchlist"),
    placeholderData: (prev) => prev,
  });

  const addMutation = useMutation({
    mutationFn: (symbol: string) =>
      apiFetch<{ symbol: string; added: boolean }>(`/watchlist/${symbol}`, {
        method: "POST",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const removeMutation = useMutation({
    mutationFn: (symbol: string) => apiFetch<void>(`/watchlist/${symbol}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const items = data?.items ?? [];

  let body;
  if (!data && isError) {
    body = <p className="mt-3 text-sm">Your watchlist could not be loaded right now.</p>;
  } else if (!data) {
    body = <div role="status" aria-busy="true" aria-label="Loading your watchlist" className="mt-3 h-24 rounded-xl bg-sunk" />;
  } else if (items.length === 0) {
    body = <p className="mt-3 text-sm">Your watchlist is empty. Add a ticker above to start tracking it here.</p>;
  } else {
    body = (
      <ul className="mt-2">
        {items.map((item) => (
          <WatchRow
            key={item.symbol}
            item={item}
            removing={removeMutation.isPending && removeMutation.variables === item.symbol}
            onRemove={() => removeMutation.mutate(item.symbol)}
          />
        ))}
      </ul>
    );
  }

  return (
    <Card aria-labelledby="watchlist-title">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="watchlist-title" className="text-[1.0625rem] font-bold">
          Your watchlist
        </h2>
        {items.length > 0 && <span className="tabular text-[0.8125rem] text-muted">{items.length === 1 ? "1 name" : `${items.length} names`}</span>}
      </div>
      <p className="mt-1 text-[0.8125rem] text-muted">
        Names you follow here, so their quotes stay fresh. The scan&apos;s own watchlist is on{" "}
        <Link href="/research/universe" className="font-semibold text-content underline underline-offset-2">
          Universe
        </Link>
        .
      </p>
      <AddSymbol onPick={(symbol) => addMutation.mutate(symbol)} disabled={addMutation.isPending} />
      {addMutation.isError && (
        <p role="alert" className="mt-2 text-sm">
          That name could not be added. Nothing changed.
        </p>
      )}
      {removeMutation.isError && (
        <p role="alert" className="mt-2 text-sm">
          That name could not be removed. It is still on your watchlist.
        </p>
      )}
      {body}
    </Card>
  );
}

function WatchRow({ item, removing, onRemove }: { item: WatchlistItem; removing: boolean; onRemove: () => void }) {
  const price = item.price?.value;
  const facts: ReactNode[] = [
    item.iv_rank == null ? (
      <span key="iv">
        IV rank <Hatched />
      </span>
    ) : (
      <span key="iv" className="tabular">{`IV rank ${item.iv_rank.toFixed(1)}`}</span>
    ),
    item.checks.evaluable === 0 ? (
      <span key="checks">
        Checks <Hatched />
      </span>
    ) : (
      <span key="checks" className="tabular">{`${item.checks.passed} of ${item.checks.evaluable} checks pass`}</span>
    ),
  ];
  if (item.next_earnings) facts.push(<span key="earn">{`Earnings ${shortDate(item.next_earnings)}`}</span>);

  return (
    <li className="flex items-center gap-3 border-t border-border py-2.5 first:border-t-0">
      <Link href={`/stock/${item.symbol}`} className="min-w-0 flex-1 py-1">
        <span className="flex items-baseline gap-2">
          <span className="font-bold">{item.symbol}</span>
          <span className="truncate text-[0.8125rem] text-muted">{item.name}</span>
        </span>
        <span className="mt-0.5 block text-[0.8125rem] text-muted">
          {facts.map((f, i) => (
            <span key={i}>
              {i > 0 && " · "}
              {f}
            </span>
          ))}
        </span>
      </Link>
      <div className="shrink-0 text-right">
        <div className="tabular font-semibold">{price == null ? <Hatched /> : formatMoneyCell(price)}</div>
        <div className="mt-0.5 flex items-center justify-end gap-1.5 text-[0.8125rem] text-muted">
          {item.price?.stale && <StatusWord tone="flag">Delayed</StatusWord>}
          {item.change_pct == null ? (
            <span>
              Day <Hatched />
            </span>
          ) : (
            <span className="tabular">{`${signedPct(item.change_pct)} today`}</span>
          )}
        </div>
      </div>
      <button
        type="button"
        disabled={removing}
        onClick={onRemove}
        aria-label={`Remove ${item.symbol}`}
        className="inline-flex min-h-11 shrink-0 items-center rounded-full px-3 text-[0.8125rem] font-semibold text-muted enabled:hover:bg-sunk enabled:hover:text-content disabled:opacity-50 md:min-h-9"
      >
        Remove
      </button>
    </li>
  );
}

/**
 * Typeahead over the research symbol directory (`GET /research/search`), the same pattern
 * `components/universe/AddSymbol.tsx` uses: a typo cannot reach the write route because the caller only
 * ever picks a real hit. This per-user list has no order consequence, so a pick fires at once with no
 * dialog. `disabled` blanks the input while an add is in flight, so a fast double-pick cannot fire two
 * POSTs.
 */
function AddSymbol({ onPick, disabled = false }: { onPick: (symbol: string) => void; disabled?: boolean }) {
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const id = useId();

  useEffect(() => {
    if (!term.trim()) {
      setHits([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const data = await apiFetch<SearchResponse>(`/research/search?q=${encodeURIComponent(term)}`);
        setHits(data.results);
      } catch {
        setHits([]);
      }
    }, 200);
    return () => clearTimeout(t);
  }, [term]);

  return (
    <div className="mt-3 max-w-sm">
      <label htmlFor={id} className={FIELD_LABEL}>
        Follow a name
      </label>
      <input
        id={id}
        value={term}
        disabled={disabled}
        onChange={(e) => setTerm(e.target.value)}
        placeholder="Add a symbol"
        autoComplete="off"
        className={`${FIELD} mt-1 w-full disabled:opacity-50`}
      />
      {hits.length > 0 && (
        <ul className="mt-1 rounded-xl border border-control bg-surface py-1">
          {hits.map((h) => (
            <li key={h.symbol}>
              <button
                type="button"
                onClick={() => {
                  setTerm("");
                  setHits([]);
                  onPick(h.symbol);
                }}
                className="flex min-h-11 w-full items-center gap-3 px-3 text-left text-sm hover:bg-sunk focus-visible:bg-sunk md:min-h-9"
              >
                <span className="tabular font-semibold">{h.symbol}</span>
                <span className="min-w-0 flex-1 truncate text-muted">{h.name}</span>
                {h.is_etf && <StatusWord>ETF</StatusWord>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {term.trim() && hits.length === 0 && <p className="mt-1 text-[0.8125rem] text-muted">No ticker matches yet.</p>}
    </div>
  );
}
