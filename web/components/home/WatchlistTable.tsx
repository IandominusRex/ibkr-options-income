"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";

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

export function WatchlistTable() {
  const qc = useQueryClient();
  const { data } = useQuery({
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
    mutationFn: (symbol: string) =>
      apiFetch<void>(`/watchlist/${symbol}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
  });

  const items = data?.items ?? [];

  return (
    <div>
      <AddSymbol
        onPick={(symbol) => addMutation.mutate(symbol)}
        disabled={addMutation.isPending}
      />

      {items.length === 0 ? (
        <p className="mt-3 text-sm text-muted">
          Your watchlist is empty. Add a ticker above to start tracking it here.
        </p>
      ) : (
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-2 font-medium">Symbol</th>
              <th className="py-2 font-medium">Price</th>
              <th className="py-2 font-medium">Day</th>
              <th className="py-2 font-medium">IV rank</th>
              <th className="py-2 font-medium">Checks</th>
              <th className="py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {items.map((item) => (
              <tr key={item.symbol}>
                <td className="py-2">
                  <Link
                    href={`/stock/${item.symbol}`}
                    className="font-mono text-content hover:text-focus"
                  >
                    {item.symbol}
                  </Link>
                  <div className="text-xs text-muted">{item.name}</div>
                </td>
                <td className="py-2 tabular">
                  {item.price?.value != null ? (
                    <span className="text-content">
                      ${item.price.value.toFixed(2)}
                      <span className="ml-1 text-xs text-unknown">
                        {relativeAge(item.price.as_of)}
                        {item.price.stale ? " · delayed" : ""}
                      </span>
                    </span>
                  ) : (
                    <span className="text-unknown">n/a</span>
                  )}
                </td>
                <td className="py-2 tabular">
                  {item.change_pct == null ? (
                    <span className="text-unknown">n/a</span>
                  ) : (
                    <ChangePct value={item.change_pct} />
                  )}
                </td>
                <td className="py-2 tabular">
                  {item.iv_rank == null ? (
                    <span className="text-unknown">n/a</span>
                  ) : (
                    <span className="text-content">{item.iv_rank.toFixed(1)}</span>
                  )}
                </td>
                <td className="py-2 text-xs text-muted">
                  {item.checks.passed} of {item.checks.evaluable}
                </td>
                <td className="py-2 text-right">
                  <button
                    type="button"
                    disabled={removeMutation.isPending && removeMutation.variables === item.symbol}
                    onClick={() => removeMutation.mutate(item.symbol)}
                    className="text-xs text-muted enabled:hover:text-loss disabled:cursor-default disabled:opacity-50"
                  >
                    remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/**
 * Typeahead over the research symbol directory (`GET /research/search`), the
 * same pattern `components/universe/AddSymbol.tsx` uses for `would_own`/
 * `watchlist` there — a typo cannot reach the write route because the
 * caller only ever picks a real hit. Unlike that universe watchlist, this
 * per-user watchlist has no order consequence, so a pick fires immediately
 * with no confirmation dialog, matching the existing `remove` control.
 * `disabled` (driven by the caller's `addMutation.isPending`) blanks the
 * input while an add is in flight — without it, a fast double-pick could
 * fire two POSTs for the same or different symbols with no feedback that
 * either was already in flight.
 */
function AddSymbol({
  onPick,
  disabled = false,
}: {
  onPick: (symbol: string) => void;
  disabled?: boolean;
}) {
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);

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

  return (
    <div>
      <input
        value={term}
        disabled={disabled}
        onChange={(e) => setTerm(e.target.value)}
        placeholder="Add a symbol"
        aria-label="Add a symbol to your watchlist"
        autoComplete="off"
        className="w-full max-w-xs rounded-sm border border-border bg-background px-2 py-1 font-mono text-sm text-content outline-none placeholder:text-muted focus-visible:border-focus disabled:opacity-50"
      />
      {hits.length > 0 && (
        <ul className="mt-1 max-w-xs rounded-sm border border-border bg-surface">
          {hits.map((h) => (
            <li key={h.symbol}>
              <button
                type="button"
                onClick={() => {
                  setTerm("");
                  setHits([]);
                  onPick(h.symbol);
                }}
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
    </div>
  );
}

function ChangePct({ value }: { value: number }) {
  const sign = value > 0 ? "+" : "";
  const cls = value > 0 ? "text-gain" : value < 0 ? "text-loss" : "text-muted";
  return <span className={cls}>{`${sign}${value.toFixed(2)}%`}</span>;
}