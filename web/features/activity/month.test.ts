import { describe, expect, it } from "vitest";
import { currentMonth, earliestMonth, monthLabel, parseMonth, shiftMonth } from "./month";

describe("months", () => {
  it("takes the month from a New York day", () => {
    expect(currentMonth("2026-10-23")).toBe("2026-10");
  });
  it("accepts a real month no later than this one", () => {
    expect(parseMonth("2026-09", "2026-10")).toBe("2026-09");
    expect(parseMonth("2026-10", "2026-10")).toBe("2026-10");
  });
  it("falls back to this month for junk, a month that does not exist and a future month", () => {
    for (const raw of [null, undefined, "", "abc", "2026-13", "2026-00", "2026-9", "2026-10-01", "2027-01"]) {
      expect(parseMonth(raw, "2026-10"), String(raw)).toBe("2026-10");
    }
  });
  it("steps across a year boundary in both directions", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-10", 0)).toBe("2026-10");
    expect(shiftMonth("2026-10", -13)).toBe("2025-09");
  });
  it("names a month in words", () => {
    expect(monthLabel("2026-10")).toBe("October 2026");
    expect(monthLabel("2025-01")).toBe("January 2025");
  });
  it("finds the month the system began from the curve's start date", () => {
    expect(earliestMonth("2026-06-24")).toBe("2026-06");
    expect(earliestMonth(null)).toBeNull();
    expect(earliestMonth(undefined)).toBeNull();
    expect(earliestMonth("soon")).toBeNull();
  });
});
