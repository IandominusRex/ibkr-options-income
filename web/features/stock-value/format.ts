import { listWords, price } from "@/components/value/format";
import { UNKNOWN } from "@/lib/format";
import type {
  Segment,
  ValueClaudeList,
  ValueDriver,
  ValueKillTrigger,
  ValueList,
  ValuePlan,
  ValueReevaluation,
  ValueTicker,
  Watch,
} from "./types";

export { listWords, price };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Nov 3, 2026" from "2026-11-03" or an ISO timestamp (the date part, never shifted by a time zone). */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return UNKNOWN;
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
}

const VERDICTS: Record<string, string> = {
  READY: "Ready",
  WATCH: "Watch",
  WAIT: "Wait",
  NO: "No",
  UNKNOWN: "Not scored",
  NOT_APPLICABLE: "Not applicable",
};

export function verdictWords(v: string): string {
  return VERDICTS[v] ?? humanize(v);
}

/** Who decided a list's verdict, in a sentence. Claude's is named as Claude's, with the baseline beside it. */
export function decidedByWords(l: Pick<ValueList, "decided_by" | "baseline_verdict" | "verdict">): string {
  if (l.decided_by === "claude") {
    return `Claude's verdict decides this. Python's baseline is ${verdictWords(l.baseline_verdict)}.`;
  }
  return "Python's rules decide this.";
}

/** "snake_case" or "dq.filing_age" as lower-case words; the prefix before a dot is dropped. */
export function humanize(id: string): string {
  const tail = id.includes(".") ? id.slice(id.lastIndexOf(".") + 1) : id;
  return tail
    .split("_")
    .map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w))
    .join(" ");
}

const ACRONYMS = new Set(["fcf", "sbc", "roe", "rote", "roic", "ebit", "ebitda", "eps", "pe", "dcf", "ttm", "sec"]);

export function capitalised(s: string): string {
  return s.length === 0 ? s : s[0]!.toUpperCase() + s.slice(1);
}

/** "13.1%" from a fraction; null stays unknown. */
export function fractionPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return UNKNOWN;
  return `${(v * 100).toFixed(1)}%`;
}

/** "30%" from a number already in percent. */
export function pointsPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return UNKNOWN;
  return `${Number.isInteger(v) ? v : v.toFixed(1)}%`;
}

const PLAIN = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

/** A plain number, up to four decimals, for a gate reading or a driver; unknown stays unknown. */
export function plainNumber(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return UNKNOWN;
  return PLAIN.format(v);
}

/** The exit plan as segments: "stop $X · sell half at $Y · then trail". A level we lack is a hatched n/a. */
export function planSegments(plan: ValuePlan | null | undefined): Segment[] | null {
  if (!plan) return null;
  const out: Segment[] = [];
  out.push(plan.stop == null ? { text: "stop n/a", unknown: true } : { text: `stop ${price(plan.stop)}` });
  if (plan.half_sold) {
    out.push({ text: "half sold" });
  } else {
    const target = plan.effective_fair_value ?? plan.fair_value;
    out.push(target == null ? { text: "sell half n/a", unknown: true } : { text: `sell half at ${price(target)}` });
  }
  out.push({ text: "then trail" });
  return out;
}

export function gateStateWord(state: string): string {
  switch (state) {
    case "pass":
      return "Pass";
    case "fail":
      return "Fail";
    case "not_applicable":
      return "Not applicable";
    default:
      return UNKNOWN;
  }
}

/** What a gate read against the bar it was held to: "reads 3.2, bar 2". */
export function gateReading(value: number | null | undefined, threshold: number | null | undefined): string | null {
  if (value == null && threshold == null) return null;
  const read = value == null ? "reads n/a" : `reads ${plainNumber(value)}`;
  return threshold == null ? read : `${read}, bar ${plainNumber(threshold)}`;
}

const METHOD_NAMES: Record<string, string> = {
  A: "Earnings power",
  B: "Cash-flow DCF",
  C: "Own-history percentile",
  D: "Growth DCF",
  PTBV: "Justified price to tangible book",
};

/** A valuation method's name in words (spec 6.5's A, B, C, D and P/TBV). */
export function methodName(code: string): string {
  return METHOD_NAMES[code] ?? capitalised(humanize(code));
}

const METHOD_STATE: Record<string, string> = {
  absent: "not available",
  unreliable: "unreliable",
  not_applicable: "not applicable",
};

export function methodStateWords(state: string): string | null {
  return METHOD_STATE[state] ?? null;
}

const REASON_WORDS: Record<string, string> = {
  mos_below_required: "the margin of safety is below what the regime asks",
  timing_not_ready: "the entry timing is not ready",
  health_gate_failed: "a health gate failed",
  data_unreliable: "the data is not reliable enough yet",
  earnings_within_window: "earnings are inside the entry window",
};

export function reasonCodeWords(code: string): string {
  return REASON_WORDS[code] ?? humanize(code);
}

/** One driver Claude chose: what it picked, what Python used and, when it moved, which bound held it. */
export function driverWords(d: ValueDriver): string {
  const name = capitalised(humanize(d.name));
  if (d.clamped) {
    const bound = d.bound === "lo" ? "lower" : d.bound === "hi" ? "upper" : null;
    const held = bound ? ` (held at its ${bound} bound, taken from the company's own filed history)` : " (held at a bound)";
    return `${name}: Claude chose ${plainNumber(d.chosen)}, Python used ${plainNumber(d.used)}${held}`;
  }
  return `${name}: ${plainNumber(d.used ?? d.chosen)}`;
}

/** A kill trigger's distance from firing, in words. */
export function killWords(t: ValueKillTrigger): string {
  if (t.state === "fired") return "It has fired.";
  if (t.state === "unknown" || t.state == null) return "Distance n/a.";
  if (t.distance_pct == null) return "Distance n/a.";
  return `${pointsPct(Math.round(t.distance_pct * 10) / 10)} of room left before it fires.`;
}

export function killStateWord(state: string | null | undefined): string {
  switch (state) {
    case "fired":
      return "Fired";
    case "near":
      return "Near";
    case "far":
      return "Far";
    default:
      return UNKNOWN;
  }
}

const NOTE_LABELS: Record<string, string> = {
  thesis: "Claude's thesis",
  bear_case: "Claude's bear case",
  review: "Claude's review",
  why_cheap: "Claude's reason it is cheap",
  profile: "Claude's profile",
};
export const NOTE_ORDER = ["thesis", "bear_case", "review", "why_cheap", "profile"];

export function noteLabel(kind: string): string {
  return NOTE_LABELS[kind] ?? `Claude's ${humanize(kind)}`;
}

/** The scorecard date a read of Claude's is set beside. Says when Claude read and flags a newer scorecard. */
export function readWords(readAt: string | null | undefined, asOf: string): string {
  if (!readAt) return `Scorecard of ${shortDate(asOf)}`;
  const read = shortDate(readAt);
  const moved = readAt.slice(0, 10) < asOf.slice(0, 10);
  return moved
    ? `Read ${read}, before the scorecard of ${shortDate(asOf)}`
    : `Read ${read}, against the scorecard of ${shortDate(asOf)}`;
}

/** "read Nov 4, 2026": the short note that sits beside each of Claude's labels. */
export function readShort(readAt: string | null | undefined): string | undefined {
  return readAt ? `read ${shortDate(readAt)}` : undefined;
}

/** The file's age in one line. */
export function fileAgeWords(t: Pick<ValueTicker, "computed" | "age_days">, asOf: string | null | undefined): string {
  if (t.computed === "now") return "Worked out just now from the latest filings";
  if (t.computed === "pending") return "Fetching the filings";
  const date = shortDate(asOf);
  if (t.age_days == null) return `Scorecard of ${date}`;
  const age = t.age_days === 0 ? "today" : t.age_days === 1 ? "1 day old" : `${t.age_days} days old`;
  return `Scorecard of ${date}, ${age}`;
}

const POLL_PENDING_MS = 5_000;
const POLL_READ_MS = 15_000;
export const READ_WATCH_MS = 10 * 60_000;

/**
 * How long until the block asks again. A file still being worked out is asked for every 5 s, like the
 * stock page's other pending sections. After "Run Claude's analysis" is queued the block looks every
 * 15 s for ten minutes, or until Claude's read time changes, whichever comes first.
 */
export function refetchMs(data: ValueTicker | undefined, watch: Watch | null, now: number): number | false {
  if (data?.computed === "pending") return POLL_PENDING_MS;
  if (watch && now - watch.since < READ_WATCH_MS) {
    const readAt = data?.claude?.read_at ?? null;
    if (readAt === watch.readAt) return POLL_READ_MS;
  }
  return false;
}

function stopOf(blob: Record<string, unknown>): number | null {
  const direct = blob.stop;
  if (typeof direct === "number") return direct;
  const nested = blob.value;
  if (nested && typeof nested === "object") {
    const s = (nested as Record<string, unknown>).stop;
    if (typeof s === "number") return s;
  }
  for (const v of Object.values(blob)) {
    if (v && typeof v === "object") {
      const s = (v as Record<string, unknown>).stop;
      if (typeof s === "number") return s;
    }
  }
  return null;
}

/** A re-evaluation's plan change: "stop $120.00 to $135.00", "stop $120.00, unchanged" or the plain gap. */
export function planChangeWords(r: Pick<ValueReevaluation, "plan_before" | "plan_after">): Segment {
  const before = stopOf(r.plan_before ?? {});
  const after = stopOf(r.plan_after ?? {});
  if (before == null && after == null) return { text: "stop n/a", unknown: true };
  if (before != null && after != null) {
    return before === after ? { text: `stop ${price(after)}, unchanged` } : { text: `stop ${price(before)} to ${price(after)}` };
  }
  return after != null ? { text: `stop set at ${price(after)}` } : { text: `stop was ${price(before)}, now n/a`, unknown: true };
}

/** What fired, one trigger per piece: "move: down 8%". */
export function triggerWords(triggers: ValueReevaluation["triggers"]): string {
  const parts = (triggers ?? []).map((t) => {
    const kind = typeof t.kind === "string" ? t.kind : "trigger";
    const detail = typeof t.detail === "string" ? t.detail : "";
    return detail ? `${kind}: ${detail}` : kind;
  });
  return parts.join("; ");
}

/** A Claude list, found by list name; undefined when Claude read no verdict for it. */
export function claudeFor(lists: ValueClaudeList[] | undefined, name: string): ValueClaudeList | undefined {
  return (lists ?? []).find((c) => c.list_name === name);
}
