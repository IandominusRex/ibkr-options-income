"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
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

function List({ label, items }: { label: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1">
      <span className="text-xs font-semibold tracking-[0.04em] text-muted">{label}</span>
      <ul className="max-w-[65ch] list-disc space-y-1 pl-5">
        {items.map((item, i) => (
          <li key={i} className="text-sm">
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
        <Button variant="secondary" disabled={generating} onClick={() => generate.mutate()}>
          {generating ? "Generating..." : "Generate summary"}
        </Button>
        {generate.isError && (
          <p role="alert" className="text-sm">
            Generation failed. The rest of the page is unaffected; try again later.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="max-w-[65ch] text-sm">{summary.thesis}</p>

      <div className="grid gap-4">
        <List label="Bull points" items={summary.bull_points} />
        <List label="Bear points" items={summary.bear_points} />
      </div>

      {summary.watch_items.length > 0 && (
        <List label="Watch items" items={summary.watch_items} />
      )}

      {summary.caveats.length > 0 && (
        <div className="space-y-1 rounded-xl bg-sunk px-3 py-2.5">
          <span className="text-xs font-semibold tracking-[0.04em] text-muted">Caveats</span>
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
        Written by {summary.model}, a language model that decides nothing · data as of {relativeAge(summary.data_as_of)}
        {state === "stale" ? " · stale" : ""}
      </p>
    </div>
  );
}