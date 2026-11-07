import { Hatched } from "@/features/stock-value/parts";

type SectorMover = { symbol: string; change_pct: number | null };

type Props = {
  sector: string;
  count: number;
  changePct: number | null;
  best: SectorMover;
  worst: SectorMover;
  avgIvRank: number | null;
  ivRankCount: number;
};

/**
 * One sector as a row of the Sectors card (web overhaul Part 6, restyled in place): the name and its
 * average IV rank with how many names it averages, then the day's move and the count, then the best and
 * worst movers. A move is signed but never green or red, because a sector's move is a price, not money
 * (web/DESIGN.md Colors). Unknown is a hatched n/a, never 0.
 */
export function SectorCard({ sector, count, changePct, best, worst, avgIvRank, ivRankCount }: Props) {
  return (
    <li className="border-t border-border py-3 first:border-t-0">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="min-w-0 truncate text-[0.9375rem] font-bold">{sector}</h3>
        <span className="shrink-0 text-sm">
          IV rank{" "}
          {avgIvRank == null ? (
            <Hatched />
          ) : (
            <>
              <span className="tabular font-semibold">{avgIvRank.toFixed(1)}</span>{" "}
              <span className="tabular text-[0.8125rem] text-muted">{ivRankCount === 1 ? "(1 name)" : `(${ivRankCount})`}</span>
            </>
          )}
        </span>
      </div>
      <p className="mt-0.5 text-[0.8125rem] text-muted">
        <span className="tabular">{count === 1 ? "1 name" : `${count} names`}</span>
        {" · "}
        {changePct == null ? (
          <>
            day <Hatched />
          </>
        ) : (
          <>
            <span className="tabular">{signedPct(changePct)}</span> today
          </>
        )}
      </p>
      <p className="mt-0.5 text-[0.8125rem] text-muted">
        Best <Mover m={best} />
        {" · "}
        worst <Mover m={worst} />
      </p>
    </li>
  );
}

function Mover({ m }: { m: SectorMover }) {
  // The API sends "-" for a sector with no priced name: that is unknown as a whole, not a ticker.
  if (m.symbol === "-") return <Hatched />;
  return (
    <>
      <span className="font-semibold text-content">{m.symbol}</span>{" "}
      {m.change_pct == null ? <Hatched /> : <span className="tabular">{signedPct(m.change_pct)}</span>}
    </>
  );
}

function signedPct(v: number): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}
