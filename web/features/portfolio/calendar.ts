import type { CalendarEntry } from "@/components/portfolio/types";
import { usd, weekdayDate } from "./format";

export const HORIZONS = [14, 30, 45, 90, 180] as const;
export const DEFAULT_HORIZON = 45; // the API's own default

export const expiryLabel = weekdayDate;

export function daysLeft(dte: number): string {
  return dte <= 0 ? "today" : dte === 1 ? "1 day left" : `${dte} days left`;
}

/**
 * What happens at expiry. `unknown` is a named state, not a default: the API was told never to
 * report an unknown consequence as an expiry worthless, and this never does either.
 */
export function consequenceSentence(c: CalendarEntry["consequence"]): string {
  switch (c) {
    case "assigned":
      return "Assigned: shares change hands";
    case "called_away":
      return "Called away: shares are sold";
    case "expires_worthless":
      return "Expires worthless";
    case "unknown":
      return "Consequence unknown";
  }
}

export function entryTitle(e: Pick<CalendarEntry, "underlying" | "strike" | "right">): string {
  return `${e.underlying} ${usd(e.strike)} ${e.right === "P" ? "put" : "call"}`;
}
