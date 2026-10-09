import type { NewsPost } from "./types";
import { whenLabel } from "./format";
import { VerdictPill } from "./VerdictPill";

export function NewsCard({ post, chartUri }: { post: NewsPost; chartUri?: string | null }) {
  const p = post.payload;
  const e = p.explanation;
  return (
    <article className="space-y-3 rounded-md bg-surface p-4" data-testid={`news-card-${post.id}`}>
      <header className="flex flex-wrap items-baseline gap-2">
        <span aria-hidden="true">{p.emoji}</span>
        <h3 className="text-sm font-medium text-content">{p.title}</h3>
        <span className="font-mono text-xs text-muted tabular">{whenLabel(p.when)}</span>
        {post.critical && <span className="text-xs text-unknown">critical</span>}
      </header>
      {p.image_url && (
        // A plain <img>: next/image would need every news site's host in remotePatterns.
        // no-referrer so a third-party thumbnail never learns which page showed it.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={p.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="max-h-48 w-full rounded-sm object-cover" />
      )}
      {p.headline_line && (
        <p className="text-sm text-content">
          {p.headline_line}
          {p.links.length > 0 && <span className="text-muted"> · </span>}
          {p.links.slice(0, 3).map((l, i) => (
            <span key={l.url}>
              {i > 0 && <span className="text-muted"> · </span>}
              <a href={l.url} target="_blank" rel="noreferrer" className="underline decoration-border hover:text-content">{l.name}</a>
            </span>
          ))}
        </p>
      )}
      {p.facts_line && <p className="font-mono text-xs text-muted tabular">{p.facts_line}</p>}
      {p.grid.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-left text-muted"><tr><th className="pr-4">Asset</th><th className="pr-4">Textbook</th><th>Actual (15m)</th></tr></thead>
          <tbody>
            {p.grid.map((g) => (
              <tr key={g.asset} data-testid={`grid-${g.asset}`} className="border-t border-border">
                <td className="py-1 pr-4 capitalize">{g.asset}</td>
                <td className="py-1 pr-4">{g.textbook ?? "·"}</td>
                <td className="py-1 font-mono tabular">{g.actual ?? "pending"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {p.grid_note && <p className="text-xs text-muted">{p.grid_note}</p>}
      {e && (
        <div className="space-y-1 text-sm">
          <p className="text-content">{e.read}</p>
          <p className="text-muted">Bull: {e.bull} · Bear: {e.bear}</p>
          <VerdictPill verdict={e.verdict} confidence={e.confidence} />
          {e.book_impact && <p className="text-content">Your book: {e.book_impact}</p>}
          {e.setup_impact && <p className="text-content">Setups: {e.setup_impact}</p>}
          {p.trimmed && <p className="text-xs text-unknown">Some unsupported numbers were removed.</p>}
        </div>
      )}
      {p.llm_note && <p className="text-xs text-muted">{p.llm_note}</p>}
      {p.sections.map((s) => (
        <section key={s.title} className="space-y-1">
          <h4 className="text-xs font-medium text-muted">{s.title}</h4>
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
      {p.updates.map((u) => <p key={u} className="text-xs text-muted">{u}</p>)}
      {chartUri && (
        // A data: URI from GET /news/posts/{id}; next/image adds nothing for an inline PNG.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={chartUri} alt={`${post.subject ?? "News"} chart`} className="w-full rounded-sm" />
      )}
    </article>
  );
}
