const DATE = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const WEEKDAY = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });

/** "$180", "$72.5": a strike or a basis in dollars, cents only when there are some. */
export const usd = (v: number): string => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

/** "Oct 15, 2026" for a "YYYY-MM-DD" date, read as written so it never shifts with the viewer's zone. */
export const shortDate = (iso: string): string => DATE.format(new Date(`${iso}T00:00:00Z`));

/** "Fri, Nov 20" for a "YYYY-MM-DD" date, read as written. */
export const weekdayDate = (iso: string): string => WEEKDAY.format(new Date(`${iso}T00:00:00Z`));
