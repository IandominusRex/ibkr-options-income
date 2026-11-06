import { StatusWord } from "@/components/ui/StatusWord";
import { UNKNOWN } from "@/lib/format";

export type CheckRowState = "PASS" | "FAIL" | "UNKNOWN" | "NOT_APPLICABLE";

export type CheckRowProps = {
  statement: string;
  state: CheckRowState;
  actual: number | null;
  threshold: number | number[] | null;
  note?: string | null;
};

const STATE_LABEL: Record<CheckRowState, string> = {
  PASS: "Pass",
  FAIL: "Fail",
  UNKNOWN: "Unknown",
  NOT_APPLICABLE: "Not applicable",
};

function formatNumber(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

function formatThreshold(threshold: number | number[] | null): string {
  if (threshold === null) return UNKNOWN;
  if (Array.isArray(threshold)) {
    return `${formatNumber(threshold[0])} – ${formatNumber(threshold[1])}`;
  }
  return formatNumber(threshold);
}

/**
 * One check (web overhaul Part 5): the question, its state as a word (a flag word for Fail), then
 * what it read against the bar on a line of its own, so a phone never squeezes the question into a
 * column. An unknown reading is a hatched n/a, never 0.
 */
export function CheckRow({ statement, state, actual, threshold, note }: CheckRowProps) {
  return (
    <div
      data-testid="check-row"
      data-state={state.toLowerCase()}
      className="border-t border-border py-2.5 text-sm first:border-t-0"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0">{statement}</p>
        <StatusWord tone={state === "FAIL" ? "flag" : "neutral"}>{STATE_LABEL[state]}</StatusWord>
      </div>
      <p className="tabular mt-0.5 text-[0.8125rem] text-muted">
        Reads{" "}
        <span className={actual === null ? "hatch px-1 text-unknown" : "font-semibold text-content"}>
          {actual === null ? UNKNOWN : formatNumber(actual)}
        </span>
        {" · bar "}
        <span className={threshold === null ? "hatch px-1 text-unknown" : "text-content"}>{formatThreshold(threshold)}</span>
      </p>
      {note && <p className="mt-0.5 text-[0.8125rem] text-muted">{note}</p>}
    </div>
  );
}
