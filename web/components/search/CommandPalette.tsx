"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

type Hit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
type SearchResponse = { as_of: string; query: string; results: Hit[] };

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-scrim pt-[15vh]">
      <div className="w-full max-w-xl rounded-lg bg-elevated p-2">
        <input
          autoFocus
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="Search a ticker or company"
          className="w-full bg-transparent px-3 py-2 font-mono text-sm text-content outline-none placeholder:text-muted"
        />
        <ul className="max-h-80 overflow-y-auto">
          {hits.map((h) => (
            <li key={h.symbol}>
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  router.push(`/stock/${h.symbol}`);
                }}
                className="flex w-full items-baseline gap-3 rounded px-3 py-2 text-left hover:bg-surface focus-visible:bg-surface"
              >
                <span className="tabular font-mono text-sm text-content">{h.symbol}</span>
                <span className="truncate text-sm text-muted">{h.name}</span>
                {h.is_etf && <span className="ml-auto text-[11px] text-muted">ETF</span>}
              </button>
            </li>
          ))}
          {term.trim() && hits.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted">No match</li>
          )}
        </ul>
      </div>
    </div>
  );
}