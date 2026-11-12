import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import type { NewsPost } from "./types";
import { whenLabel } from "./format";
import { VerdictPill } from "./VerdictPill";

/**
 * One news post (restyled in place, web overhaul Part 7). The content is the news service's own: the
 * title, the headline line and its sources, the facts, the reaction grid, the sections and the updates.
 * The explanation is written by the news model (Claude, or the local model when Claude cannot be
 * reached), so it sits in a labelled block and is named by that model, not as Claude's.
 */
export function NewsCard({ post, chartUri }: { post: NewsPost; chartUri?: string | null }) {
  const p = post.payload;
  const e = p.explanation;
  return (
    <Card as="article" className="space-y-3" data-testid={`news-card-${post.id}`}>
      <header className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span aria-hidden="true">{p.emoji}</span>
        <h3 className="min-w-0 text-[1.0625rem] font-bold">{p.title}</h3>
        {post.critical && <StatusWord tone="flag">Critical</StatusWord>}
        <span className="tabular basis-full text-[0.8125rem] text-muted">{whenLabel(p.when)}</span>
      </header>
      {p.image_url && (
        // A plain <img>: next/image would need every news site's host in remotePatterns.
        // no-referrer so a third-party thumbnail never learns which page showed it.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={p.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="max-h-48 w-full rounded-xl object-cover" />
      )}
      {p.headline_line && (
        <p className="max-w-[65ch] text-sm">
          {p.headline_line}
          {p.links.length > 0 && <span className="text-muted"> · </span>}
          {p.links.slice(0, 3).map((l, i) => (
            <span key={l.url}>
              {i > 0 && <span className="text-muted"> · </span>}
              <a href={l.url} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2">
                {l.name}
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </span>
          ))}
        </p>
      )}
      {p.facts_line && <p className="tabular text-[0.8125rem] text-muted">{p.facts_line}</p>}
      {p.grid.length > 0 && (
        <table className="w-full text-[0.8125rem]">
          <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted"><tr><th className="pb-1 pr-4 font-semibold">Asset</th><th className="pb-1 pr-4 font-semibold">Textbook</th><th className="pb-1 font-semibold">Actual (15m)</th></tr></thead>
          <tbody>
            {p.grid.map((g) => (
              <tr key={g.asset} data-testid={`grid-${g.asset}`} className="border-t border-border">
                <td className="py-1 pr-4 capitalize">{g.asset}</td>
                <td className="py-1 pr-4">{g.textbook ?? "·"}</td>
                <td className="tabular py-1">{g.actual ?? "pending"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {p.grid_note && <p className="text-[0.8125rem] text-muted">{p.grid_note}</p>}
      {e && (
        <div className="space-y-1.5 rounded-xl bg-sunk px-3 py-2 text-sm" data-testid="news-reading">
          <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
            <span className="font-semibold">The news model&apos;s reading</span>
            <span className="text-muted">Claude, or the local model when Claude cannot be reached; it trades nothing</span>
          </p>
          <p className="max-w-[65ch]">{e.read}</p>
          <p className="max-w-[65ch] text-muted">Bull: {e.bull} · Bear: {e.bear}</p>
          <VerdictPill verdict={e.verdict} confidence={e.confidence} />
          {e.book_impact && <p className="max-w-[65ch]">Your book: {e.book_impact}</p>}
          {e.setup_impact && <p className="max-w-[65ch]">Setups: {e.setup_impact}</p>}
          {p.trimmed && <p className="text-xs text-muted">Some unsupported numbers were removed.</p>}
        </div>
      )}
      {p.llm_note && <p className="text-[0.8125rem] text-muted">{p.llm_note}</p>}
      {p.sections.map((s) => (
        <section key={s.title} className="space-y-1">
          <h4 className="text-xs font-semibold tracking-[0.04em] text-muted">{s.title}</h4>
          {s.items.some((it) => it.read || it.verdict) && (
            <p className="text-xs text-muted">The readings and verdicts below are the news model&apos;s.</p>
          )}
          <ul className="space-y-1 text-sm">
            {s.items.map((it, i) => (
              <li key={i}>
                {it.text}
                {it.read && <span className="block text-muted">{it.read}</span>}
                {it.verdict && <VerdictPill verdict={it.verdict} />}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {p.updates.map((u, i) => <p key={i} className="text-[0.8125rem] text-muted">{u}</p>)}
      {chartUri && (
        // A data: URI from GET /news/posts/{id}; next/image adds nothing for an inline PNG.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={chartUri} alt={`${post.subject ?? "News"} chart`} className="w-full rounded-xl" />
      )}
    </Card>
  );
}
