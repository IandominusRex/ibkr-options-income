import { isCalendarDay } from "@/features/trades/time";
import type { IndexRegime, LeveragedLimit } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MINUS = "−";

const ET_PARTS = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZone: "America/New_York",
});

/** "Oct 22, 11:00 AM ET": an instant in New York time, the zone always said. */
export function etLabel(iso: string | null | undefined): string {
  const t = iso ? Date.parse(iso) : Number.NaN;
  if (Number.isNaN(t)) return "time n/a";
  const part = Object.fromEntries(ET_PARTS.formatToParts(new Date(t)).map((p) => [p.type, p.value]));
  return `${part.month} ${part.day}, ${part.hour}:${part.minute} ${String(part.dayPeriod).toUpperCase()} ET`;
}

/** "Oct 12" for a "YYYY-MM-DD" day, read as written so the date never shifts with the viewer's zone. */
export function shortDay(isoDate: string): string {
  if (!isCalendarDay(isoDate)) return "date n/a";
  const [, m, d] = isoDate.split("-");
  return `${MONTHS[Number(m) - 1]} ${Number(d)}`;
}

/** "40%", "12.5%": one decimal at most, no trailing .0. */
export function percent(p: number): string {
  return `${Number(p.toFixed(1))}%`;
}

/** A move with its sign ("+1.2%", "−2.0%", a real minus); a genuine zero stays unsigned. */
export function signedPercent(p: number): string {
  const body = `${Math.abs(p).toFixed(1)}%`;
  if (Number(Math.abs(p).toFixed(1)) === 0) return body;
  return `${p > 0 ? "+" : MINUS}${body}`;
}

const NO_DATA = "no_data";
const STALE = "stale:";

/** One plain line for an index: its daily base, then what raised it today or eased it. */
export function regimeLine(ix: IndexRegime): string {
  const reasons = ix.escalated_by ?? [];
  const raised = reasons.filter((r) => r !== NO_DATA && !r.startsWith(STALE));
  const parts = [`Daily base ${ix.base}`];
  if (raised.length) parts.push(`raised today by ${raised.join(", ")}`);
  if (ix.eased_by_bottoming) parts.push("eased one step by a bottoming signal");
  if (reasons.includes(NO_DATA)) parts.push("no market data yet");
  if (reasons.some((r) => r.startsWith(STALE))) parts.push("some inputs are out of date");
  return `${parts.join(", ")}.`;
}

/** Leveraged-ETF ceilings in words, one sentence per multiple and ceiling, 3x before 2x. */
export function leveragedLines(rows: LeveragedLimit[]): string[] {
  const groups = new Map<string, { leverage: number; calm: number; stressed: number; symbols: string[] }>();
  for (const r of rows) {
    const key = `${r.leverage}|${r.calm_fraction}|${r.stressed_fraction}`;
    const g = groups.get(key) ?? { leverage: r.leverage, calm: r.calm_fraction, stressed: r.stressed_fraction, symbols: [] };
    g.symbols.push(r.symbol);
    groups.set(key, g);
  }
  return [...groups.values()]
    .sort((a, b) => b.leverage - a.leverage || b.calm - a.calm || b.stressed - a.stressed)
    .map(
      (g) =>
        `${g.leverage}x (${g.symbols.sort().join(", ")}): ${percent(g.calm * 100)} of the regime's size when calm, ` +
        `${percent(g.stressed * 100)} when the name or its market is under stress.`,
    );
}

export function cutSentence(mode: "applied" | "record_only", account: "paper" | "live"): string {
  return `Claude's size cuts: ${mode === "applied" ? "applied" : "recorded only"} (${account}).`;
}
