"use client";

import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";

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

  if (items.length === 0) {
    return (
      <div>
        <p className="text-sm text-muted">
          Your watchlist is empty. Add a ticker from the search box to start tracking it
          here.
        </p>
      </div>
    );
  }

  return (
    <table className="w-full text-sm">
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
                onClick={() => removeMutation.mutate(item.symbol)}
                className="text-xs text-muted hover:text-loss"
              >
                remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ChangePct({ value }: { value: number }) {
  const sign = value > 0 ? "+" : "";
  const cls = value > 0 ? "text-gain" : value < 0 ? "text-loss" : "text-muted";
  return <span className={cls}>{`${sign}${value.toFixed(2)}%`}</span>;
}