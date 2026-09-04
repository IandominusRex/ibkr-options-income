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
  // genuine zero) — rendering "0 samples" next to a real score would be a fabricated
  // number, exactly what this panel exists to avoid.
  count: number | null;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted">{label}</span>
      <span className={`tabular text-sm ${score === null ? "text-unknown" : "text-content"}`}>
        {score === null ? UNKNOWN : score.toFixed(1)}
      </span>
      <span className={`text-xs ${count === null ? "text-unknown" : "text-muted"}`}>
        {count === null ? `${UNKNOWN} samples` : `${count} samples`}
      </span>
    </div>
  );
}

export function SentimentPanel({ data }: { data: Sentiment }) {
  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-4">
        <span className={`tabular text-2xl ${data.overall === null ? "text-unknown" : "text-content"}`}>
          {data.overall === null ? UNKNOWN : data.overall.toFixed(1)}
        </span>
        <span className="text-sm text-muted">{data.label}</span>
        {data.delta_1d !== null && (
          <span className={`tabular text-xs ${data.delta_1d >= 0 ? "text-gain" : "text-loss"}`}>
            {data.delta_1d >= 0 ? "+" : ""}
            {data.delta_1d.toFixed(1)} 1d
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-4">
        <Score label="StockTwits" score={data.stocktwits} count={data.stocktwits_msgs} />
        <Score label="News" score={data.news} count={data.news_count} />
        <Score label="Reddit" score={data.reddit} count={null} />
      </div>
    </div>
  );
}