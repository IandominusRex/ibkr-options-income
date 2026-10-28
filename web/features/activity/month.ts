/** New York months as "YYYY-MM" strings (the Pay view's `?month=`). */
const MONTH = /^(\d{4})-(0[1-9]|1[0-2])$/;
const NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** The month a "YYYY-MM-DD" New York day falls in. */
export const currentMonth = (today: string): string => today.slice(0, 7);

/** A real month no later than this one; anything else (none, junk, a future month) is this month. */
export function parseMonth(raw: string | null | undefined, current: string): string {
  return raw && MONTH.test(raw) && raw <= current ? raw : current;
}

export function shiftMonth(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number);
  const index = y * 12 + (m - 1) + n;
  return `${String(Math.floor(index / 12)).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}

/** "October 2026". */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${NAMES[m - 1]} ${y}`;
}

/** The month the system began, from the curve's start date; null when it is not known. */
export function earliestMonth(startsAt: string | null | undefined): string | null {
  return startsAt && /^\d{4}-\d{2}-\d{2}/.test(startsAt) ? startsAt.slice(0, 7) : null;
}
