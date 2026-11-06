import { listWords, price } from "@/components/value/format";
import type { components } from "@/lib/api-types";
import type { ValueTicker } from "@/features/stock-value/types";

/** The stock page's read of `GET /research/{symbol}` (src/api/models/research.py). */
export type Analysis = components["schemas"]["AnalysisResponse"];

/** A level drawn across the price chart as a dashed rule, with its label on the price axis. */
export type ChartLine = { price: number; title: string };

const PRICED = new Set(["READY", "WATCH", "WAIT"]);

/**
 * Whether the value book has a view of this name worth leading with: a list the book would buy at a
 * price (Ready, Watch or Wait), or shares it holds. Anything else (no file, a name it does not score,
 * every list No) puts the value block at the foot of the page instead.
 */
export function valueLeads(t: ValueTicker | undefined): boolean {
  if (!t?.available || !t.file || t.file.not_applicable_reason) return false;
  if (t.plan) return true;
  return (t.file.lists ?? []).some((l) => PRICED.has(l.verdict));
}

/**
 * The value book's levels for the chart (web overhaul Part 5, HANDOFF V6): per priced list its fair
 * value (the effective one) and entry ceiling; for a held name the half sale (at the plan's fair value,
 * until it is made) and the stop. A level with no number is not drawn; two levels at the same price
 * share one line and one label. With two priced lists each label names its list.
 */
export function valueLines(t: ValueTicker | undefined): ChartLine[] {
  if (!t?.available || !t.file || t.file.not_applicable_reason) return [];
  const priced = (t.file.lists ?? []).filter((l) => PRICED.has(l.verdict));
  const both = priced.length > 1;
  const raw: ChartLine[] = [];
  for (const l of priced) {
    const suffix = both ? ` (${listWords(l.list_name)})` : "";
    if (l.effective_fair_value != null) raw.push({ price: l.effective_fair_value, title: `Fair value${suffix}` });
    if (l.entry_ceiling != null) raw.push({ price: l.entry_ceiling, title: `Entry ceiling${suffix}` });
  }
  const plan = t.plan;
  if (plan) {
    const target = plan.effective_fair_value ?? plan.fair_value;
    if (!plan.half_sold && target != null) raw.push({ price: target, title: "Half sale" });
    if (plan.stop != null) raw.push({ price: plan.stop, title: "Stop" });
  }
  const merged: ChartLine[] = [];
  for (const line of raw) {
    const same = merged.find((m) => Math.abs(m.price - line.price) < 0.005);
    if (same) {
      if (!same.title.split(", ").includes(line.title)) same.title = `${same.title}, ${line.title}`;
    } else {
      merged.push({ ...line });
    }
  }
  return merged.map((m) => ({ price: m.price, title: `${m.title} ${price(m.price)}` }));
}

/** "Alphabet Inc. · NASDAQ · ETF": the name line under the ticker. Empty while loading. */
export function nameLine(a: Pick<Analysis, "name" | "exchange" | "is_etf"> | undefined): string {
  if (!a) return "";
  return [a.name, a.exchange ?? null, a.is_etf ? "ETF" : null].filter((x): x is string => !!x).join(" · ");
}
