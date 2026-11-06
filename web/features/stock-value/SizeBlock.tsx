import { StatusWord } from "@/components/ui/StatusWord";
import { sharesWord } from "@/components/value/format";
import {
  fractionPct,
  gateStateWord,
  listWords,
  pointsPct,
  price,
  reasonCodeWords,
  sizeSegment,
  trancheWords,
} from "./format";
import { Hatched, Segments, Subhead } from "./parts";
import type { ValueFile, ValuePlan } from "./types";

/**
 * "How much, and when?": per list the timing state, the margin of safety the regime asks against
 * what this name has, the entry ceiling and why the baseline said what it said; for a held name,
 * what the book holds and its tranche plan; per priced list the size tier its margin of safety
 * reaches (web overhaul Part 5).
 */
export function SizeBlock({ file, plan }: { file: ValueFile; plan: ValuePlan | null | undefined }) {
  const lists = file.lists ?? [];
  const tranches = trancheWords(plan);
  return (
    <section aria-labelledby="vb-size" className="mt-4 border-t border-border pt-3">
      <h3 id="vb-size" className="text-sm font-bold">
        How much, and when?
      </h3>
      {plan && (
        <p className="mt-2 text-sm">
          You hold {sharesWord(plan.shares)}
          {plan.avg_cost != null && ` at an average cost of ${price(plan.avg_cost)}`} in the {listWords(plan.list_name)}{" "}
          list.
        </p>
      )}
      {plan &&
        (tranches ? (
          <p className="mt-1 text-sm">{tranches}</p>
        ) : (
          <p className="mt-1 text-sm">
            Tranches bought <Hatched />
          </p>
        ))}
      {lists.map((l) => {
        const timing = gateStateWord(l.timing ?? "unknown");
        const size = sizeSegment(l);
        return (
          <div key={l.list_name} className="mt-4 first:mt-2">
            <Subhead>{listWords(l.list_name)}</Subhead>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm">
              <span>Timing</span>
              {timing === "n/a" ? <Hatched /> : <StatusWord tone={l.timing === "fail" ? "flag" : "neutral"}>{timing}</StatusWord>}
            </p>
            <p className="mt-1 text-sm">
              The margin of safety asked now is {pointsPct(l.required_mos_pct)}; this name has{" "}
              {l.mos == null ? <Hatched /> : fractionPct(l.mos)}.
            </p>
            <p className="tabular mt-1 text-sm">
              Entry ceiling {l.entry_ceiling == null ? <Hatched /> : price(l.entry_ceiling)}
            </p>
            {size && (
              <p className="tabular mt-1 text-sm">
                <Segments parts={[size]} />
              </p>
            )}
            {(l.reasons ?? []).length > 0 && (
              <p className="mt-1 text-[0.8125rem] text-muted">
                Why the baseline says {l.baseline_verdict.toLowerCase()}: {(l.reasons ?? []).map(reasonCodeWords).join("; ")}.
              </p>
            )}
          </div>
        );
      })}
    </section>
  );
}
