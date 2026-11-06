import { StatusWord } from "@/components/ui/StatusWord";
import { relativeAge } from "@/lib/format";

type NewsItem = {
  title: string;
  url: string | null;
  published_at: string | null;
  source: string | null;
  sentiment: number | null;
};

export function sentimentLabel(v: number | null): string {
  if (v === null) return "n/a";
  if (v > 0.2) return "bullish";
  if (v > 0.05) return "lean bullish";
  if (v < -0.2) return "bearish";
  if (v < -0.05) return "lean bearish";
  return "neutral";
}

export function sentimentTint(v: number | null): string {
  if (v === null) return "text-unknown";
  if (v > 0.05) return "text-gain";
  if (v < -0.05) return "text-loss";
  return "text-muted";
}

export function NewsPanel({ items }: { items: NewsItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted">No recent headlines.</p>;
  }

  // The tone is a word in a neutral status chip: it is not money, so it is never green or red on
  // this page (web overhaul Part 5). `sentimentTint` stays for the position page's headlines.
  return (
    <ul>
      {items.map((item, i) => {
        const age = relativeAge(item.published_at);
        return (
          <li key={i} className="flex items-start gap-3 border-t border-border py-2.5 text-sm first:border-t-0">
            <div className="min-w-0 flex-1">
              {item.url ? (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-semibold underline-offset-2 hover:underline"
                >
                  {item.title}
                </a>
              ) : (
                <span className="font-semibold">{item.title}</span>
              )}
              <div className="mt-0.5 flex flex-wrap gap-x-2 text-[0.8125rem] text-muted">
                {item.source && <span>{item.source}</span>}
                {age && <span>{age}</span>}
              </div>
            </div>
            <StatusWord>{sentimentLabel(item.sentiment)}</StatusWord>
          </li>
        );
      })}
    </ul>
  );
}