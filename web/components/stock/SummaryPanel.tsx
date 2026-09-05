"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";

type Summary = {
  thesis: string;
  bull_points: string[];
  bear_points: string[];
  watch_items: string[];
  caveats: string[];
  model: string;
  data_as_of: string;
};

type SummaryResponse = {
  as_of: string;
  symbol: string;
  state: "ready" | "stale" | "unavailable" | "pending";
  summary: Summary | null;
  reason: string | null;
};

function List({ label, items, accent }: { label: string; items: string[]; accent?: string }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1">
      <span className="text-xs font-medium tracking-wide text-muted">{label}</span>
      <ul className="space-y-1">
        {items.map((item, i) => (
          <li key={i} className={`text-sm ${accent ?? "text-content"}`}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SummaryPanel({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const upper = symbol.toUpperCase();

  const { data } = useQuery<SummaryResponse>({
    queryKey: ["summary", upper],
    queryFn: () => apiFetch<SummaryResponse>(`/research/${upper}/summary`),
  });

  const generate = useMutation({
    mutationFn: () => apiFetch<SummaryResponse>(`/research/${upper}/summary`, { method: "POST" }),
    onSuccess: (resp) => {
      qc.setQueryData(["summary", upper], resp);
    },
  });

  const state = data?.state ?? "unavailable";
  const summary = data?.summary;
  const generating = generate.isPending;

  if (!summary) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted">
          {data?.reason ?? "No summary yet. Generate one on demand."}
        </p>
        <button
          type="button"
          disabled={generating}
          onClick={() => generate.mutate()}
          className="rounded-md bg-elevated px-4 py-2 text-sm text-content transition-opacity hover:opacity-80 disabled:opacity-50"
        >
          {generating ? "Generating..." : "Generate summary"}
        </button>
        {generate.isError && (
          <p className="text-sm text-loss">
            Generation failed. The rest of the page is unaffected; try again later.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-content">{summary.thesis}</p>

      <div className="grid gap-5 sm:grid-cols-2">
        <List label="Bull points" items={summary.bull_points} accent="text-gain" />
        <List label="Bear points" items={summary.bear_points} accent="text-loss" />
      </div>

      {summary.watch_items.length > 0 && (
        <List label="Watch items" items={summary.watch_items} />
      )}

      {summary.caveats.length > 0 && (
        <div className="space-y-1 rounded-md bg-surface px-4 py-3">
          <span className="text-xs font-medium tracking-wide text-muted">Caveats</span>
          <ul className="space-y-1">
            {summary.caveats.map((c, i) => (
              <li key={i} className="text-sm text-muted">
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-muted">
        {summary.model} · data as of {relativeAge(summary.data_as_of)}
        {state === "stale" ? " · stale" : ""}
      </p>
    </div>
  );
}