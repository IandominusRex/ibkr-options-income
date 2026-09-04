import { relativeAge } from "@/lib/format";

type NewsItem = {
  title: string;
  url: string | null;
  published_at: string | null;
  source: string | null;
  sentiment: number | null;
};

function sentimentLabel(v: number | null): string {
  if (v === null) return "n/a";
  if (v > 0.2) return "bullish";
  if (v > 0.05) return "lean bullish";
  if (v < -0.2) return "bearish";
  if (v < -0.05) return "lean bearish";
  return "neutral";
}

function sentimentTint(v: number | null): string {
  if (v === null) return "text-unknown";
  if (v > 0.05) return "text-gain";
  if (v < -0.05) return "text-loss";
  return "text-muted";
}

export function NewsPanel({ items }: { items: NewsItem[] }) {
  if (items.length === 0) {
    return (
      <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
        No recent headlines.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {items.map((item, i) => {
        const label = sentimentLabel(item.sentiment);
        const tint = sentimentTint(item.sentiment);
        const age = relativeAge(item.published_at);
        return (
          <li key={i} className="flex items-start gap-3 text-sm">
            <div className="flex-1">
              {item.url ? (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-content hover:text-focus"
                >
                  {item.title}
                </a>
              ) : (
                <span className="text-content">{item.title}</span>
              )}
              <div className="mt-0.5 flex gap-2 text-xs text-muted">
                {item.source && <span>{item.source}</span>}
                {age && <span>{age}</span>}
              </div>
            </div>
            <span className={`tabular shrink-0 rounded bg-elevated px-2 py-0.5 text-xs ${tint}`}>
              {label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}