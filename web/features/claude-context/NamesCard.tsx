import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusWord } from "@/components/ui/StatusWord";
import { FigureLines } from "./FigureLines";
import { etLabel, shortDay } from "./format";
import type { ClaudeContext, Dossier } from "./types";

const KIND: Record<Dossier["kind"], string> = { stock: "Stock", etf: "ETF", leveraged_etf: "Leveraged ETF" };

/** Python's health label. A fund carries none ("n/a" from the API: it does not apply), so nothing
 *  is shown for it; a stock whose fundamentals could not be read shows a hatched n/a. */
function Health({ d }: { d: Dossier }) {
  if (d.health === "n/a") return null;
  if (d.health === "unknown") {
    return (
      <span className="text-xs font-semibold tracking-[0.04em] text-muted">
        Health <span className="hatch px-1.5 text-unknown">n/a</span>
      </span>
    );
  }
  return <StatusWord tone={d.health === "weak" ? "flag" : "neutral"}>{`Health: ${d.health}`}</StatusWord>;
}

const LABEL = "text-xs font-semibold tracking-[0.04em] text-muted";

function Notes({ d }: { d: Dossier }) {
  if (!d.prose_at) {
    return <p className="mt-2 text-[0.8125rem] text-muted">Claude has not written notes for this name yet.</p>;
  }
  if (d.stale) {
    return (
      <p className="mt-2 flex flex-wrap items-center gap-2 text-[0.8125rem] text-muted">
        <StatusWord tone="flag">Stale</StatusWord>
        <span>Notes are from {etLabel(d.prose_at)}; the last rebuild failed.</span>
      </p>
    );
  }
  return <p className="mt-2 text-[0.8125rem] text-muted">Notes rebuilt {etLabel(d.prose_at)}</p>;
}

function Name({ d }: { d: Dossier }) {
  const events = d.events ?? [];
  const evidence = d.story_evidence ?? [];
  const facts = d.facts ?? [];
  const why = d.health_why ?? [];
  return (
    <li aria-labelledby={`name-${d.symbol}`} className="border-t border-border py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h3 id={`name-${d.symbol}`} className="text-[1.0625rem] font-bold">
          {d.symbol}
        </h3>
        {d.held && <StatusWord>Held</StatusWord>}
        <span className="text-[0.8125rem] text-muted">{KIND[d.kind]}</span>
        <Health d={d} />
      </div>
      {why.length > 0 && <p className="mt-1 text-[0.8125rem] text-muted">{why[0]}</p>}

      {d.story ? (
        <p className="mt-2 break-words text-sm">
          <span className={`${LABEL} mr-1.5`}>Claude&apos;s story</span>
          {d.story}
          {evidence.length > 0 && (
            <span className="tabular ml-1.5 font-mono text-[0.8125rem] text-muted">Evidence: {evidence.join(", ")}</span>
          )}
        </p>
      ) : (
        <p className="mt-2 text-sm">
          <span className={`${LABEL} mr-1.5`}>Claude&apos;s story</span>
          <span className="hatch mr-1.5 px-1.5 text-unknown">n/a</span>No story right now.
        </p>
      )}

      {events.length > 0 && (
        <div className="mt-1 flex gap-1.5 text-sm">
          <span className={`${LABEL} pt-0.5`}>Upcoming</span>
          <ul className="grid min-w-0 gap-0.5">
            {events.map((e) => (
              <li key={e.id} className="break-words">
                {`${shortDay(e.on)} · ${e.title}`}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Notes d={d} />

      <div className="mt-1">
        <Disclosure summary={<span className="text-sm font-semibold">Profile and numbers</span>} tone="plain">
          <p className={LABEL}>Claude&apos;s summary, general knowledge</p>
          {d.profile ? (
            <p className="break-words text-sm">{d.profile}</p>
          ) : (
            <p className="text-sm">
              <span className="hatch mr-1.5 px-1.5 text-unknown">n/a</span>No summary written yet.
            </p>
          )}
          {facts.length > 0 && (
            <FigureLines
              label={`${d.symbol} numbers`}
              rows={facts.map((f) => ({ label: f.label, value: f.display }))}
            />
          )}
          {events.length > 0 && (
            <ul className="mt-3 grid gap-1 text-[0.8125rem] text-muted">
              {events.map((e) => (
                <li key={e.id} className="break-words">
                  {`${shortDay(e.on)} found in the news (${e.evidence}): “${e.quote}”`}
                </li>
              ))}
            </ul>
          )}
        </Disclosure>
      </div>
    </li>
  );
}

/** One row per name the book cares about: Python's health and numbers, Claude's story and summary. */
export function NamesCard({ ctx }: { ctx: ClaudeContext }) {
  const dossiers = ctx.dossiers ?? [];
  const missing = ctx.without_notes ?? [];
  return (
    <Card aria-labelledby="names-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 id="names-title" className="text-[1.0625rem] font-bold">
          Names
        </h2>
        {ctx.available && dossiers.length > 0 && (
          <span className="text-[0.8125rem] text-muted">{dossiers.length} with notes</span>
        )}
      </div>
      {!ctx.available ? (
        <p className="mt-2 text-sm">The news service has not written anything yet, so there are no notes.</p>
      ) : (
        <>
          <p className="mt-1 text-[0.8125rem] text-muted">
            What the news service keeps on each name the book cares about. Python writes the numbers and the health
            label; Claude writes the story and the summary. Held names come first.
          </p>
          {dossiers.length === 0 ? (
            <p className="mt-2 text-sm">No notes have been written yet.</p>
          ) : (
            <ul className="mt-2">
              {dossiers.map((d) => (
                <Name key={d.symbol} d={d} />
              ))}
            </ul>
          )}
          {missing.length > 0 && (
            <p className="mt-2 text-[0.8125rem] text-muted">No notes yet for {missing.join(", ")}.</p>
          )}
        </>
      )}
    </Card>
  );
}
