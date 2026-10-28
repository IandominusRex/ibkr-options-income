/**
 * Calendar-day arithmetic on `YYYY-MM-DD` strings, in UTC so no viewer's zone can move a day.
 * The date picker is the only reader; a day is never a `Date` the caller has to keep.
 */

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

export type Ymd = { y: number; m: number; d: number };

export function parseIso(iso: string): Ymd | null {
  const hit = ISO.exec(iso);
  if (!hit) return null;
  const [y, m, d] = [Number(hit[1]), Number(hit[2]), Number(hit[3])];
  // A real calendar day only: 2026-02-31 is not one.
  return new Date(Date.UTC(y, m - 1, d)).getUTCDate() === d && m >= 1 && m <= 12 ? { y, m, d } : null;
}

export function toIso({ y, m, d }: Ymd): string {
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function daysInMonth(y: number, m: number): number {
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

/** 0 for Monday through 6 for Sunday: the week runs Monday-first, as the market week does. */
export function weekdayIndex({ y, m, d }: Ymd): number {
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

export function addDays(iso: string, n: number): string {
  const p = parseIso(iso);
  if (!p) return iso;
  const t = new Date(Date.UTC(p.y, p.m - 1, p.d + n));
  return toIso({ y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() });
}

/** The same day n months on, or the month's last day when it has no such day (Jan 31 + 1 = Feb 28). */
export function addMonths(iso: string, n: number): string {
  const p = parseIso(iso);
  if (!p) return iso;
  const index = p.y * 12 + (p.m - 1) + n;
  const y = Math.floor(index / 12);
  const m = (index % 12) + 1;
  return toIso({ y, m, d: Math.min(p.d, daysInMonth(y, m)) });
}

/** Each day of a month as a row of seven, `null` for the blanks around it. */
export function monthRows(y: number, m: number): (string | null)[][] {
  const lead = weekdayIndex({ y, m, d: 1 });
  const cells: (string | null)[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= daysInMonth(y, m); d++) cells.push(toIso({ y, m, d }));
  while (cells.length % 7 !== 0) cells.push(null);
  const rows: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) rows.push(cells.slice(i, i + 7));
  return rows;
}

const SHORT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const LONG = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
const MONTH = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

const at = (iso: string) => {
  const p = parseIso(iso);
  return p ? new Date(Date.UTC(p.y, p.m - 1, p.d)) : null;
};

/** "Oct 28, 2026", or "" for a value that is not a day. */
export function shortDay(iso: string): string {
  const t = at(iso);
  return t ? SHORT.format(t) : "";
}

/** "Wednesday, October 28, 2026": a day button's name. */
export function longDay(iso: string): string {
  const t = at(iso);
  return t ? LONG.format(t) : "";
}

export function monthTitle(y: number, m: number): string {
  return MONTH.format(new Date(Date.UTC(y, m - 1, 1)));
}
