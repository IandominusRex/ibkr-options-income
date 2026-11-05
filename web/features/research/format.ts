import { kindOf } from "@/lib/strategy";
import { price } from "@/components/value/format";
import { capitalised, humanize, reasonCodeWords } from "@/features/stock-value/format";
import type { AssessedResponse, BarLayout, BarPoint, TopItem } from "./types";

export { fractionPct, listWords, verdictWords } from "@/features/stock-value/format";

const MAX_CARDS = 10;
const RANK: Record<string, number> = { READY: 0, WATCH: 1, WAIT: 2 };

/** READY, then WATCH, then WAIT; the API's order (its rank) is kept inside a verdict; at most ten. */
export function readyFirst(items: TopItem[]): TopItem[] {
  return items
    .map((it, i) => ({ it, i }))
    .sort((a, b) => (RANK[a.it.verdict] ?? 3) - (RANK[b.it.verdict] ?? 3) || a.i - b.i)
    .slice(0, MAX_CARDS)
    .map((x) => x.it);
}

function ids(list: string): string {
  return list
    .split(",")
    .map((s) => humanize(s.trim()))
    .join(", ");
}

/** One of Python's baseline reasons (src/value/scorecard.py) as a plain sentence. */
export function reasonSentence(raw: string): string {
  const r = raw.trim();
  let m = /^health gate (failed|unknown): (.+)$/.exec(r);
  if (m) return `A health gate ${m[1] === "failed" ? "failed" : "is unknown"}: ${ids(m[2]!)}.`;
  m = /^entry rule (\w+)$/.exec(r);
  if (m) return m[1] === "unknown" ? "The entry rule is unknown." : "The entry rule does not pass.";
  m = /^price ([\d.]+) above the entry ceiling ([\d.]+)$/.exec(r);
  if (m) return `The price, ${price(Number(m[1]))}, is above the entry ceiling, ${price(Number(m[2]))}.`;
  m = /^cheap enough; timing (\w+)$/.exec(r);
  if (m) return `Cheap enough, but the timing check is ${m[1] === "unknown" ? "unknown" : "not passing"}.`;
  if (r === "healthy, cheap enough, timing passes") return "Healthy, cheap enough, and the timing passes.";
  if (r === "no fair value") return "No fair value yet.";
  const words = /^[a-z_]+$/.test(r) ? reasonCodeWords(r) : r;
  const s = capitalised(words);
  return /[.!?]$/.test(s) ? s : `${s}.`;
}

/** The file's age in one line; null when the API does not know it. */
export function ageWords(days: number | null | undefined): string | null {
  if (days === null || days === undefined) return null;
  if (days === 0) return "Scorecard from today";
  return days === 1 ? "Scorecard 1 day old" : `Scorecard ${days} days old`;
}

// A label is about 5.5rem wide; on a 300px track that is 28% of it.
const LABEL_PCT = 28;
const GAP_PCT = 1;

function interval(pct: number): { align: BarPoint["align"]; lo: number; hi: number } {
  if (pct - LABEL_PCT / 2 < 0) return { align: "start", lo: pct, hi: pct + LABEL_PCT };
  if (pct + LABEL_PCT / 2 > 100) return { align: "end", lo: pct - LABEL_PCT, hi: pct };
  return { align: "center", lo: pct - LABEL_PCT / 2, hi: pct + LABEL_PCT / 2 };
}

/**
 * Places the known levels along one track and gives each label a row where it overlaps no other.
 * A level the API has no number for is not drawn (never at zero): it is named in `unknown`.
 * The half sale is the same price as fair value today, so the two share a point.
 */
export function layoutBar(it: TopItem): BarLayout {
  type Raw = { kind: BarPoint["kind"]; names: string[]; value: number };
  const raws: Raw[] = [];
  const unknown: string[] = [];
  const add = (kind: BarPoint["kind"], name: string, value: number | null | undefined) => {
    if (value === null || value === undefined || Number.isNaN(value)) unknown.push(name);
    else raws.push({ kind, names: [name], value });
  };
  add("price", "Price", it.price);
  add("fair", "Fair value", it.fair_value);
  add("ceiling", "Entry ceiling", it.entry_ceiling);
  add("stop", "Stop", it.stop);
  const fair = raws.find((r) => r.kind === "fair");
  if (it.half_sell != null && fair && fair.value === it.half_sell) fair.names.push("Half sale");
  else add("half", "Half sale", it.half_sell);

  if (raws.length === 0) return { points: [], unknown, lanes: 0 };
  const lo = Math.min(...raws.map((r) => r.value));
  const hi = Math.max(...raws.map((r) => r.value));
  const pad = (hi - lo) * 0.12;
  const span = hi - lo + 2 * pad;
  const at = (v: number) => (span === 0 ? 50 : ((v - (lo - pad)) / span) * 100);

  const placed: { lo: number; hi: number }[][] = [];
  const points = raws
    .map((r) => ({ ...r, pct: at(r.value) }))
    .sort((a, b) => a.pct - b.pct)
    .map((r): BarPoint => {
      const iv = interval(r.pct);
      let lane = placed.findIndex((row) => row.every((o) => iv.lo >= o.hi + GAP_PCT || iv.hi + GAP_PCT <= o.lo));
      if (lane === -1) {
        placed.push([]);
        lane = placed.length - 1;
      }
      placed[lane]!.push(iv);
      return { kind: r.kind, names: r.names, value: r.value, pct: r.pct, lane, align: iv.align };
    });
  return { points, unknown, lanes: placed.length };
}

/** A passed cash-secured-put candidate at or under the value-suggested ceiling, in the latest scan. */
export function sellPutAvailable(it: TopItem, assessed: AssessedResponse | undefined): boolean {
  const ceiling = it.put_ceiling;
  if (ceiling === null || ceiling === undefined || !assessed) return false;
  return assessed.groups.some(
    (g) =>
      g.symbol.toUpperCase() === it.symbol.toUpperCase() &&
      g.contracts.some(
        (c) =>
          c.stage === "passed" && kindOf(c.strategy, null) === "csp" && c.strike != null && c.strike <= ceiling,
      ),
  );
}

/** The stock page's value block (its title carries this id). */
export function stockValueHref(symbol: string): string {
  return `/stock/${symbol}#value-block-${symbol}`;
}

/** Trades, Assessed, the name's cash-secured puts. */
export function assessedHref(symbol: string): string {
  return `/trades?view=assessed&strategy=csp&symbol=${encodeURIComponent(symbol)}`;
}
