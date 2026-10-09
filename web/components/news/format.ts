const SGT = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Singapore", hour: "2-digit", minute: "2-digit", hour12: false });
const ET = new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
const DAY = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Singapore", weekday: "short", day: "2-digit", month: "short" });

export function whenLabel(iso: string): string {
  const d = new Date(iso);
  return `${SGT.format(d)} SGT (${ET.format(d)} ET)`;
}
export function dayLabel(iso: string): string {
  return DAY.format(new Date(iso));
}
export const VERDICT_LABEL: Record<string, string> = {
  further_downside_likely: "Further downside likely",
  further_upside_likely: "Further upside likely",
  overreaction_likely: "Overreaction likely",
  priced_in: "Priced in",
  unclear: "Unclear",
};
