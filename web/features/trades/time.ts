const TIME_ET = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
const DAY = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
/** en-CA formats as YYYY-MM-DD. */
const NEW_YORK_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });

export function timeET(iso: string): string {
  const t = Date.parse(iso);
  // Some ICU builds put a narrow no-break space before AM/PM; the label uses a plain one.
  return Number.isNaN(t) ? "time n/a" : `${TIME_ET.format(new Date(t)).replace(/[  ]/g, " ")} ET`;
}

/** True for a "YYYY-MM-DD" that is a real calendar date, so "2026-13-45" never reaches the formatters. */
export function isCalendarDay(value: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const t = new Date(Date.UTC(y, mo - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d;
}

/** "Thu, Oct 15" for a "YYYY-MM-DD" New York day (formatted in UTC so the date never shifts). */
export function dayLabel(isoDate: string): string {
  return DAY.format(new Date(`${isoDate}T00:00:00Z`));
}

/** The New York calendar day an instant falls on, or null for an unreadable one. */
export function newYorkDay(iso: string): string | null {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : NEW_YORK_DAY.format(new Date(t));
}

export function todayInNewYork(now: Date = new Date()): string {
  return NEW_YORK_DAY.format(now);
}

export function shiftDay(isoDate: string, n: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** "Thu, Oct 22 · 2:31 PM ET": an instant as a New York day and time; "time n/a" when it cannot be read. */
export function whenET(iso: string): string {
  const day = newYorkDay(iso);
  return day === null ? "time n/a" : `${dayLabel(day)} · ${timeET(iso)}`;
}
