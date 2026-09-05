"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

type UniverseResponse = {
  as_of: string;
  indexes: string[];
  watchlist: string[];
  would_own: string[];
  actively_wheeling: string[];
  sectors: Record<string, string>;
  strike_bands: Record<string, number>;
  editable: boolean;
};

export default function UniversePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["universe"],
    queryFn: () => apiFetch<UniverseResponse>("/universe"),
  });

  if (isLoading || !data) {
    return (
      <div className="px-8 py-6">
        <h1 className="font-mono text-2xl text-content">Universe</h1>
        <p className="mt-4 text-sm text-muted">Loading</p>
      </div>
    );
  }

  const wheeling = new Set(data.actively_wheeling);
  const wouldOwn = new Set(data.would_own);

  return (
    <div className="px-8 py-6">
      <header className="mb-8">
        <h1 className="font-mono text-2xl text-content">Universe</h1>
        <p className="mt-1 text-sm text-muted">
          Read-only view of the scan universe. {data.editable ? "Editable" : "Not editable in P1."}
        </p>
      </header>

      <section className="mb-10">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">Indexes</h2>
        <SymbolList
          symbols={data.indexes}
          sectors={data.sectors}
          strikeBands={data.strike_bands}
          wheeling={wheeling}
          wouldOwn={wouldOwn}
        />
      </section>

      <section className="mb-10">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">
          Watchlist ({data.watchlist.length})
        </h2>
        <SymbolList
          symbols={data.watchlist}
          sectors={data.sectors}
          strikeBands={data.strike_bands}
          wheeling={wheeling}
          wouldOwn={wouldOwn}
        />
      </section>

      <section className="mb-10">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">
          Would own — CSP allowlist ({data.would_own.length})
        </h2>
        <SymbolList
          symbols={data.would_own}
          sectors={data.sectors}
          strikeBands={data.strike_bands}
          wheeling={wheeling}
          wouldOwn={wouldOwn}
          showDipWatch
        />
      </section>

      <section className="mb-10">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">
          Actively wheeling ({data.actively_wheeling.length})
        </h2>
        <SymbolList
          symbols={data.actively_wheeling}
          sectors={data.sectors}
          strikeBands={data.strike_bands}
          wheeling={wheeling}
          wouldOwn={wouldOwn}
        />
      </section>
    </div>
  );
}

function SymbolList({
  symbols,
  sectors,
  strikeBands,
  wheeling,
  wouldOwn,
  showDipWatch = false,
}: {
  symbols: string[];
  sectors: Record<string, string>;
  strikeBands: Record<string, number>;
  wheeling: Set<string>;
  wouldOwn: Set<string>;
  showDipWatch?: boolean;
}) {
  if (symbols.length === 0) {
    return <p className="text-sm text-muted">None</p>;
  }
  return (
    <ul className="divide-y divide-border">
      {symbols.map((symbol) => {
        const band = strikeBands[symbol];
        return (
          <li key={symbol} className="flex items-center gap-3 py-2">
            <Link
              href={`/stock/${symbol}`}
              className="tabular font-mono text-sm text-content hover:text-focus"
            >
              {symbol}
            </Link>
            <span className="text-xs text-muted">
              {sectors[symbol] ?? "untagged"}
            </span>
            {wheeling.has(symbol) && (
              <span className="rounded-sm bg-elevated px-1.5 py-0.5 text-xs text-content">
                wheeling
              </span>
            )}
            {showDipWatch && wouldOwn.has(symbol) && !wheeling.has(symbol) && (
              <span className="rounded-sm bg-elevated px-1.5 py-0.5 text-xs text-muted">
                dip-watch
              </span>
            )}
            {band != null && (
              <span className="text-xs text-unknown">band {band.toFixed(2)}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}