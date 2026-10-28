import { describe, expect, it } from "vitest";
import type { CampaignSummary } from "@/components/portfolio/types";
import { legTitle, threadSub } from "./campaigns";

const leg = (over: Record<string, unknown> = {}) =>
  ({ as_of: "", candidate_id: "a", strategy: "cash_secured_put", right: "P", strike: 180, expiry: "2026-11-20", known: true, ...over }) as never;
const thread = (over: Record<string, unknown> = {}) =>
  ({ as_of: "", campaign_id: "c1", symbol: "NVDA", status: "open", opened_date: "2026-10-01", closed_date: null, legs: [leg(), leg({ candidate_id: "b" })], ...over }) as unknown as CampaignSummary;

describe("legTitle", () => {
  it("names the strategy, the strike and the side", () => {
    expect(legTitle(leg())).toBe("CSP $180 put");
    expect(legTitle(leg({ strategy: "covered_call", right: "C", strike: 72.5 }))).toBe("CC $72.5 call");
    expect(legTitle(leg({ strategy: "roll", right: "P" }))).toBe("Roll $180 put");
  });
  it("says what it does not know instead of guessing", () => {
    expect(legTitle(leg({ strike: null, right: null }))).toBe("CSP strike n/a option");
    expect(legTitle(leg({ strategy: "something_new" }))).toBe("something new $180 put");
  });
});

describe("threadSub", () => {
  it("says when an open thread began, with its leg count", () => {
    expect(threadSub(thread())).toBe("Opened Oct 1, 2026 · 2 legs");
  });
  it("gives a closed thread's span, and a singular leg", () => {
    expect(threadSub(thread({ status: "closed", closed_date: "2026-10-20", legs: [leg()] }))).toBe(
      "Oct 1, 2026 to Oct 20, 2026 · 1 leg",
    );
  });
});
