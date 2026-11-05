import { StatusWord } from "@/components/ui/StatusWord";
import {
  claudeFor,
  driverWords,
  fractionPct,
  listWords,
  methodName,
  methodStateWords,
  price,
  verdictWords,
} from "./format";
import { ClaudeLabel, Hatched, Subhead } from "./parts";
import type { ValueClaude, ValueClaudeList, ValueFile, ValueList } from "./types";

function Methods({ l }: { l: ValueList }) {
  const methods = l.methods ?? [];
  if (methods.length === 0) {
    return <p className="mt-1 text-sm text-muted">No valuation method produced a value for this list.</p>;
  }
  return (
    <ul className="mt-1">
      {methods.map((m) => {
        const state = methodStateWords(m.state);
        return (
          <li
            key={m.method}
            className="grid grid-cols-[1fr_auto] items-baseline gap-x-3 border-t border-border py-2 first:border-t-0 text-sm"
          >
            <div className="min-w-0">
              <span>{methodName(m.method)}</span>
              {m.median && <span className="ml-2"><StatusWord>Median</StatusWord></span>}
              {(state || m.detail) && (
                <div className="text-[0.8125rem] text-muted">{[state, m.detail].filter(Boolean).join(" · ")}</div>
              )}
            </div>
            <span className="tabular font-semibold">
              {m.value == null ? <Hatched /> : price(m.value)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** Claude's fair value for one list: the drivers it chose, what Python clamped, the cap, in Claude's label. */
function ClaudeValue({
  c,
  baseline,
  readNote,
}: {
  c: ValueClaudeList;
  /** Python's baseline verdict, set beside Claude's inside the box when the two differ. */
  baseline: string | null;
  readNote: string | undefined;
}) {
  const local = c.backend !== "cli";
  return (
    <div className="mt-2 rounded-xl bg-sunk px-3 py-2.5">
      <ClaudeLabel label="Claude's fair value" note={readNote} />
      <p className="tabular mt-1 text-sm font-semibold">
        {c.fair_value == null ? <Hatched /> : price(c.fair_value)}
        <span className="ml-2 font-normal text-muted">
          Python worked it out from Claude&apos;s drivers; Python&apos;s own is{" "}
          {c.python_fair_value == null ? <Hatched /> : price(c.python_fair_value)}
        </span>
      </p>
      {(c.drivers ?? []).length > 0 && (
        <ul className="mt-1 grid gap-0.5 text-[0.8125rem]">
          {(c.drivers ?? []).map((d) => (
            <li key={d.name} className="tabular">
              {driverWords(d)}
            </li>
          ))}
        </ul>
      )}
      {c.cap_applied && (
        <p className="mt-1 text-[0.8125rem]">The 1.5x cap on Python&apos;s own value bound it, so it is lower than the drivers would give.</p>
      )}
      {c.unreliable && <p className="mt-1 text-[0.8125rem]">Python marked it unreliable: {c.unreliable}</p>}
      {baseline && (
        <p className="mt-2 grid gap-0.5 border-t border-border pt-2 text-sm">
          <span>Python&apos;s baseline: {baseline}</span>
          <span>Claude&apos;s verdict: {verdictWords(c.verdict)}</span>
        </p>
      )}
      {local && (
        <p className="mt-1 text-[0.8125rem]">The local model wrote this one, so it does not decide anything.</p>
      )}
    </div>
  );
}

/**
 * "What is it worth?": per list, Python's methods side by side with the median marked, Claude's fair
 * value with the drivers it chose, any clamp and the cap, and the two verdicts side by side when
 * they differ. The reverse DCF line comes last. Python's figures are never mixed into Claude's block.
 */
export function WorthBlock({
  file,
  claude,
  readNote,
}: {
  file: ValueFile;
  claude: ValueClaude | null | undefined;
  readNote: string | undefined;
}) {
  const lists = file.lists ?? [];
  return (
    <section aria-labelledby="vb-worth" className="mt-4 border-t border-border pt-3">
      <h3 id="vb-worth" className="text-sm font-bold">
        What is it worth?
      </h3>
      {lists.map((l) => {
        const c = claudeFor(claude?.lists, l.list_name);
        const differs = c != null && c.verdict !== l.baseline_verdict;
        return (
          <div key={l.list_name} className="mt-4 first:mt-2">
            <Subhead>{listWords(l.list_name)}</Subhead>
            <Methods l={l} />
            {c && <ClaudeValue c={c} baseline={differs ? verdictWords(l.baseline_verdict) : null} readNote={readNote} />}
          </div>
        );
      })}
      <p className="mt-3 text-sm text-muted">
        {file.reverse_dcf_implied_growth == null ? (
          <>
            What the price implies for growth: <Hatched />
          </>
        ) : (
          `At this price the market expects ${fractionPct(file.reverse_dcf_implied_growth)} a year of growth.`
        )}
      </p>
    </section>
  );
}
