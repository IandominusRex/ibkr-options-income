import { UNKNOWN } from "@/lib/format";

type Sentiment = {
  overall: number | null;
  label: string;
  delta_1d: number | null;
  stocktwits: number | null;
  stocktwits_msgs: number;
  news: number | null;
  news_count: number;
  reddit: number | null;
  top_headline: string | null;
};

function Score({
  label,
  score,
  count,
}: {
  label: string;
  score: number | null;
  // null when this source has no tracked sample count at all (not the same as a
  // genuine zero): rendering "0 samples" next to a real score would be a fabricated
  // number, exactly what this panel exists to avoid.
  count: number | null;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right">
        <span className={score === null ? "tabular hatch px-1 text-unknown" : "tabular font-semibold"}>
          {score === null ? UNKNOWN : score.toFixed(1)}
        </span>
        <span className={`ml-2 text-[0.8125rem] ${count === null ? "text-unknown" : "text-muted"}`}>
          {count === null ? `${UNKNOWN} samples` : `${count} samples`}
        </span>
      </dd>
    </div>
  );
}

/** Crowd and news tone for the name (web overhaul Part 5): one figure and its word, the day's change
 * with its sign (tone is not money, so it is never green or red), then each source with its sample
 * count. Enrichment only: nothing here reaches a gate or a size. */
export function SentimentPanel({ data }: { data: Sentiment }) {
  return (
    <div>
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className={
            data.overall === null
              ? "tabular hatch px-1 text-[1.5rem] font-extrabold text-unknown"
              : "tabular text-[1.5rem] font-extrabold tracking-[-0.015em]"
          }
        >
          {data.overall === null ? UNKNOWN : data.overall.toFixed(1)}
        </span>
        <span className="text-sm font-semibold">{data.label}</span>
        {data.delta_1d !== null && (
          <span className="tabular text-[0.8125rem] text-muted">
            {data.delta_1d >= 0 ? "+" : ""}
            {data.delta_1d.toFixed(1)} 1d
          </span>
        )}
      </p>
      <dl className="mt-2">
        <Score label="StockTwits" score={data.stocktwits} count={data.stocktwits_msgs} />
        <Score label="News" score={data.news} count={data.news_count} />
        <Score label="Reddit" score={data.reddit} count={null} />
      </dl>
    </div>
  );
}
