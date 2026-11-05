import { Disclosure } from "@/components/ui/Disclosure";
import { AnalyseButton } from "./AnalyseButton";
import { NOTE_ORDER, noteLabel, readShort } from "./format";
import { ClaudeLabel } from "./parts";
import type { ValueClaude } from "./types";

/**
 * What Claude wrote about the name: its thesis, bear case and review, each labelled as Claude's with
 * the scorecard date it was read against, the filed facts it quoted (Python checked each quote against
 * the filing), and the button that asks for a fresh read. The button's label names the act and holds
 * none of Claude's text.
 */
export function ClaudeBlock({
  symbol,
  claude,
  readNote,
  onQueued,
}: {
  symbol: string;
  claude: ValueClaude | null | undefined;
  /** Claude's read time set beside the scorecard date, said once under the heading. */
  readNote: string;
  onQueued: () => void;
}) {
  const notes = [...(claude?.notes ?? [])].sort(
    (a, b) => NOTE_ORDER.indexOf(a.kind) - NOTE_ORDER.indexOf(b.kind),
  );
  const facts = claude?.facts ?? [];
  return (
    <section aria-labelledby="vb-claude" className="mt-4 border-t border-border pt-3">
      <h3 id="vb-claude" className="text-sm font-bold">
        What Claude wrote
      </h3>
      {claude && notes.length > 0 ? (
        <div className="mt-2 grid gap-3">
          <p className="text-[0.8125rem] text-muted">{readNote}</p>
          {notes.map((n) => (
            <div key={n.kind}>
              <ClaudeLabel label={noteLabel(n.kind)} note={readShort(claude.read_at)} />
              <p className="mt-0.5 max-w-[65ch] text-sm">{n.text}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted">Claude has not read {symbol} yet. Ask for a read below.</p>
      )}
      {facts.length > 0 && (
        <div className="mt-3">
          <Disclosure summary={<span className="text-sm font-semibold">Facts Claude quoted from the filings ({facts.length})</span>}>
            <ClaudeLabel label="Claude's facts" note="each quote was checked against the filing" />
            <ul className="mt-1 grid gap-2">
              {facts.map((f, i) => (
                <li key={`${f.filing}-${i}`} className="text-[0.8125rem]">
                  <span>{f.text}</span>
                  <span className="block text-muted">
                    &ldquo;{f.quote}&rdquo; · filing <span className="tabular">{f.filing}</span>
                  </span>
                </li>
              ))}
            </ul>
          </Disclosure>
        </div>
      )}
      <div className="mt-3">
        <AnalyseButton symbol={symbol} onQueued={onQueued} />
      </div>
    </section>
  );
}
