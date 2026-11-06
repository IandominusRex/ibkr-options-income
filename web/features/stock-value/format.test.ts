import { describe, expect, it } from "vitest";
import {
  decidedByWords,
  driverWords,
  fileAgeWords,
  humanize,
  killWords,
  noteLabel,
  planChangeWords,
  planSegments,
  readWords,
  refetchMs,
  shortDate,
  sizeSegment,
  trancheWords,
} from "./format";
import type { ValuePlan, ValueTicker } from "./types";

const plan = (over: Partial<ValuePlan> = {}): ValuePlan => ({
  position_id: 1, list_name: "deep_value", shares: 20, avg_cost: 150, next_exit: null, stop: 140,
  half_sold: false, fair_value: 200, effective_fair_value: 210, tranches_done: 1, tranches: 3, tranche_min_sessions: 5,
  last_tranche_on: "2026-10-20", ...over,
});

const ticker = (over: Partial<ValueTicker> = {}): ValueTicker => ({
  as_of: "2026-11-05T12:00:00Z", available: true, symbol: "GOOGL", computed: "stored", ...over,
});

describe("stock-value format", () => {
  it("writes the plan as stop, sell half at the effective value, then trail", () => {
    expect(planSegments(plan())?.map((s) => s.text).join(" · ")).toBe("stop $140.00 · sell half at $210.00 · then trail");
  });
  it("hatches a level it does not have and says half sold once it is", () => {
    const none = planSegments(plan({ stop: null }));
    expect(none?.[0]).toEqual({ text: "stop n/a", unknown: true });
    expect(planSegments(plan({ half_sold: true }))?.[1]).toEqual({ text: "half sold" });
    expect(planSegments(null)).toBeNull();
  });
  it("names who decided: Claude's verdict beside the baseline, or Python's rules", () => {
    expect(decidedByWords({ decided_by: "python", baseline_verdict: "WAIT", verdict: "WAIT" })).toBe(
      "Python's rules decide this.",
    );
    expect(decidedByWords({ decided_by: "claude", baseline_verdict: "WAIT", verdict: "READY" })).toBe(
      "Claude's verdict decides this. Python's baseline is Wait.",
    );
  });
  it("says what a driver clamp did, and which bound held it", () => {
    const text = driverWords({ name: "growth", chosen: 0.2, used: 0.1, clamped: true, bound: "hi" });
    expect(text).toContain("Growth: Claude chose 0.2, Python used 0.1");
    expect(text).toContain("upper bound");
    expect(driverWords({ name: "margin", chosen: 0.3, used: 0.3, clamped: false, bound: null })).toBe("Margin: 0.3");
  });
  it("reads a kill trigger's distance from firing, and a fired one as fired", () => {
    expect(killWords({ name: "debt", state: "far", distance_pct: 42.34 })).toBe("42.3% of room left before it fires.");
    expect(killWords({ name: "debt", state: "fired", distance_pct: null })).toBe("It has fired.");
    expect(killWords({ name: "debt", state: "unknown", distance_pct: null })).toBe("Distance n/a.");
  });
  it("labels each note as Claude's", () => {
    expect(noteLabel("thesis")).toBe("Claude's thesis");
    expect(noteLabel("bear_case")).toBe("Claude's bear case");
    expect(noteLabel("review")).toBe("Claude's review");
  });
  it("sets the read beside the scorecard date, and says when the scorecard has moved on", () => {
    expect(readWords("2026-11-04T20:00:00Z", "2026-11-04")).toBe("Read Nov 4, 2026, against the scorecard of Nov 4, 2026");
    expect(readWords("2026-11-02T20:00:00Z", "2026-11-04")).toContain("before the scorecard of Nov 4, 2026");
  });
  it("words the file's age by how it was computed", () => {
    expect(fileAgeWords(ticker({ computed: "now" }), "2026-11-05")).toBe("Worked out just now from the latest filings");
    expect(fileAgeWords(ticker({ computed: "pending" }), null)).toBe("Fetching the filings");
    expect(fileAgeWords(ticker({ age_days: 2 }), "2026-11-03")).toBe("Scorecard of Nov 3, 2026, 2 days old");
  });
  it("polls only while the file is pending, or for ten minutes after a Claude read is queued", () => {
    expect(refetchMs(ticker({ computed: "pending" }), null, 0)).toBe(5000);
    expect(refetchMs(ticker(), null, 0)).toBe(false);
    const watch = { since: 1_000, readAt: null };
    expect(refetchMs(ticker(), watch, 2_000)).toBe(15000);
    expect(refetchMs(ticker(), watch, 1_000 + 11 * 60_000)).toBe(false);
    const read = ticker({ claude: { source: "claude", read_at: "2026-11-05T12:30:00Z", lists: [], notes: [], kill_triggers: [], facts: [] } });
    expect(refetchMs(read, watch, 2_000)).toBe(false);
  });
  it("shows a re-evaluation's stop move, and never a zero for a missing stop", () => {
    expect(planChangeWords({ plan_before: { stop: 120 }, plan_after: { stop: 135 } }).text).toBe("stop $120.00 to $135.00");
    expect(planChangeWords({ plan_before: { value: { stop: 120 } }, plan_after: { value: { stop: 120 } } }).text).toBe(
      "stop $120.00, unchanged",
    );
    expect(planChangeWords({ plan_before: {}, plan_after: {} })).toEqual({ text: "stop n/a", unknown: true });
  });
  it("writes a gate id as words and keeps an acronym in capitals", () => {
    expect(humanize("health.fcf_positive")).toBe("FCF positive");
    expect(humanize("dq.filing_age")).toBe("filing age");
  });
  it("reads dates without shifting them by time zone", () => {
    expect(shortDate("2026-11-03")).toBe("Nov 3, 2026");
    expect(shortDate(null)).toBe("n/a");
  });
  it("words the size tier for a priced list only, hatched when the margin is unknown", () => {
    expect(sizeSegment({ verdict: "READY", size_pct: 5, tranches: 3 })).toEqual({
      text: "At this margin of safety a buy aims at 5% of the book's ceiling, in 3 tranches.",
    });
    expect(sizeSegment({ verdict: "WAIT", size_pct: 0, tranches: 3 })?.text).toBe(
      "This margin of safety is below the first size tier, so the book would not buy.",
    );
    expect(sizeSegment({ verdict: "WATCH", size_pct: null, tranches: 3 })).toEqual({ text: "Size if bought n/a", unknown: true });
    expect(sizeSegment({ verdict: "NO", size_pct: 8, tranches: 3 })).toBeNull();
  });
  it("words the tranche plan: what is bought and what the next one waits for", () => {
    expect(trancheWords(plan())).toBe(
      "1 of 3 tranches bought (the last on Oct 20, 2026). Tranche 2 waits for a higher low, at least 5 sessions after the last, and passes the value gate again first.",
    );
    expect(trancheWords(plan({ tranches_done: 2 }))).toBe(
      "2 of 3 tranches bought (the last on Oct 20, 2026). Tranche 3 waits for a close above the 50-day average, at least 5 sessions after the last, and passes the value gate again first.",
    );
    expect(trancheWords(plan({ tranches_done: 3 }))).toBe("All 3 tranches are bought.");
    expect(trancheWords(plan({ tranches_done: null }))).toBeNull();
    expect(trancheWords(null)).toBeNull();
  });
});
