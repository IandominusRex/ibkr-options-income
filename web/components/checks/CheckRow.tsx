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

export function CheckRow({ statement, state, actual, threshold, note }: CheckRowProps) {
  const isUnknown = state === "UNKNOWN";

  return (
    <div
      data-testid="check-row"
      data-state={state.toLowerCase()}
      className="flex items-center gap-4 border-t border-border py-2 text-sm first:border-t-0"
    >
      <div className="flex-1">
        <p className="text-content">{statement}</p>
        {note && <p className="mt-0.5 text-xs text-unknown">{note}</p>}
      </div>
      <span
        className={`tabular w-16 shrink-0 text-right ${isUnknown ? "text-unknown" : "text-content"}`}
      >
        {actual === null ? UNKNOWN : formatNumber(actual)}
      </span>
      <span className="tabular w-24 shrink-0 text-right text-xs text-muted">
        {formatThreshold(threshold)}
      </span>
      <span className={`w-24 shrink-0 text-right text-xs ${stateClass(state)}`}>
        {STATE_LABEL[state]}
      </span>
    </div>
  );
}

function stateClass(state: CheckRowState): string {
  switch (state) {
    case "PASS":
      return "text-gain";
    case "FAIL":
      return "text-loss";
    case "UNKNOWN":
      return "text-unknown";
    case "NOT_APPLICABLE":
      return "text-muted";
  }
}
