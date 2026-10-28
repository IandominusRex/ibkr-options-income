import type { CampaignLeg, CampaignSummary } from "@/components/portfolio/types";
import { shortDate, usd } from "./format";

const KIND: Record<string, string> = { cash_secured_put: "CSP", covered_call: "CC", roll: "Roll" };

/** "CSP $180 put" for a leg; a strike or side the API lacks is said, never guessed. */
export function legTitle(l: CampaignLeg): string {
  const side = l.right === "P" ? "put" : l.right === "C" ? "call" : "option";
  const strike = typeof l.strike === "number" ? usd(l.strike) : "strike n/a";
  return `${KIND[l.strategy] ?? l.strategy.replace(/_/g, " ")} ${strike} ${side}`;
}

/** When the thread began (and ended), with its leg count. */
export function threadSub(c: CampaignSummary): string {
  const n = c.legs.length;
  const legs = `${n} ${n === 1 ? "leg" : "legs"}`;
  return c.closed_date
    ? `${shortDate(c.opened_date)} to ${shortDate(c.closed_date)} · ${legs}`
    : `Opened ${shortDate(c.opened_date)} · ${legs}`;
}
