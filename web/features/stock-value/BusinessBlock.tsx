import { StatusWord } from "@/components/ui/StatusWord";
import { capitalised, gateReading, gateStateWord, humanize, killStateWord, killWords, plainNumber } from "./format";
import { ClaudeLabel, Hatched } from "./parts";
import type { ValueClaude, ValueFile, ValueGate } from "./types";

const ORDER: Record<string, number> = { fail: 0, unknown: 1, not_applicable: 2, pass: 3 };

function GateRow({ g }: { g: ValueGate }) {
  const reading = gateReading(g.value, g.threshold);
  const word = gateStateWord(g.state);
  return (
    <li className="grid grid-cols-[1fr_auto] items-baseline gap-x-3 border-t border-border py-2 first:border-t-0 text-sm">
      <div className="min-w-0">
        <span>{capitalised(humanize(g.id))}</span>
        {(reading || g.detail) && (
          <div className="tabular text-[0.8125rem] text-muted">{[reading, g.detail].filter(Boolean).join(" · ")}</div>
        )}
      </div>
      <span>
        {g.state === "fail" ? (
          <StatusWord tone="flag">{word}</StatusWord>
        ) : word === "n/a" ? (
          <Hatched />
        ) : (
          <StatusWord>{word}</StatusWord>
        )}
      </span>
    </li>
  );
}

/**
 * "Is the business still doing its job?": the quality and health gates with the value each read and
 * the bar it was held to, then the kill triggers Claude set and how far each is from firing. The
 * gates are Python's; the trigger thresholds are Claude's, and Python checks them against the
 * filings, so the block says so.
 */
export function BusinessBlock({ file, claude }: { file: ValueFile; claude: ValueClaude | null | undefined }) {
  const gates = [...(file.gates ?? [])].sort((a, b) => (ORDER[a.state] ?? 1) - (ORDER[b.state] ?? 1));
  const triggers = claude?.kill_triggers ?? [];
  return (
    <section aria-labelledby="vb-business" className="mt-4 border-t border-border pt-3">
      <h3 id="vb-business" className="text-sm font-bold">
        Is the business still doing its job?
      </h3>
      {gates.length === 0 ? (
        <p className="mt-2 text-sm text-muted">The scorecard carries no quality or health check for this name.</p>
      ) : (
        <ul className="mt-1">
          {gates.map((g) => (
            <GateRow key={g.id} g={g} />
          ))}
        </ul>
      )}
      {triggers.length > 0 && (
        <div className="mt-4">
          <ClaudeLabel label="Kill triggers Claude set, checked by Python" />
          <ul className="mt-1">
            {triggers.map((t) => (
              <li
                key={t.name}
                className="grid grid-cols-[1fr_auto] items-baseline gap-x-3 border-t border-border py-2 first:border-t-0 text-sm"
              >
                <div className="min-w-0">
                  <span>{capitalised(humanize(t.name))}</span>
                  <div className="tabular text-[0.8125rem] text-muted">
                    {t.actual == null ? "reads n/a" : `reads ${plainNumber(t.actual)}`}
                    {t.threshold != null && `, fires at ${plainNumber(t.threshold)}`}
                    {" · "}
                    {killWords(t)}
                  </div>
                </div>
                {t.state === "fired" || t.state === "near" ? (
                  <StatusWord tone="flag">{killStateWord(t.state)}</StatusWord>
                ) : t.state === "far" ? (
                  <StatusWord>{killStateWord(t.state)}</StatusWord>
                ) : (
                  <Hatched />
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
