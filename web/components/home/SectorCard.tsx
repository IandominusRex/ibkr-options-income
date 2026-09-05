import clsx from "clsx";

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

export function SectorCard({
  sector,
  count,
  changePct,
  best,
  worst,
  avgIvRank,
  ivRankCount,
}: Props) {
  return (
    <div className="bg-surface p-4">
      <header className="flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-content">{sector}</h3>
        <span className="text-xs text-muted">{count} names</span>
      </header>

      <div className="mt-3 flex items-baseline gap-2">
        {changePct == null ? (
          <span className="tabular text-sm text-unknown">n/a</span>
        ) : (
          <span className={clsx("tabular text-sm", changeClass(changePct))}>
            {signedPct(changePct)}
          </span>
        )}
        <span className="text-xs text-muted">day</span>
      </div>

      <dl className="mt-3 space-y-1 text-xs text-muted">
        <div className="flex justify-between">
          <dt>best</dt>
          <dd className="flex items-center gap-1">
            <span className="font-mono text-content">{best.symbol}</span>
            <ChangePct value={best.change_pct} />
          </dd>
        </div>
        <div className="flex justify-between">
          <dt>worst</dt>
          <dd className="flex items-center gap-1">
            <span className="font-mono text-content">{worst.symbol}</span>
            <ChangePct value={worst.change_pct} />
          </dd>
        </div>
        <div className="flex justify-between">
          <dt>avg IV rank</dt>
          <dd>
            {avgIvRank == null ? (
              <span className="text-unknown">n/a</span>
            ) : (
              <>
                <span className="tabular text-content">{avgIvRank.toFixed(1)}</span>
                <span className="ml-1 text-unknown">
                  {ivRankCount === 1 ? "(1 name)" : `(${ivRankCount})`}
                </span>
              </>
            )}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function ChangePct({ value }: { value: number | null }) {
  if (value == null) return <span className="text-unknown">n/a</span>;
  return (
    <span className={clsx("tabular", changeClass(value))}>{signedPct(value)}</span>
  );
}

function signedPct(v: number): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function changeClass(v: number): string {
  if (v > 0) return "text-gain";
  if (v < 0) return "text-loss";
  return "text-muted";
}