import { describe, expect, it } from "vitest";
import { addDays, addMonths, daysInMonth, longDay, monthRows, parseIso, shortDay, toIso, weekdayIndex } from "./dates";

describe("parseIso", () => {
  it("reads a real day", () => {
    expect(parseIso("2026-10-28")).toEqual({ y: 2026, m: 10, d: 28 });
  });
  it("refuses anything that is not a calendar day", () => {
    for (const bad of ["", "2026-02-31", "2026-13-01", "10/28/2026", "2026-1-5"]) expect(parseIso(bad)).toBeNull();
  });
  it("round-trips through toIso", () => {
    expect(toIso(parseIso("2026-01-05")!)).toBe("2026-01-05");
  });
});

describe("day arithmetic", () => {
  it("steps over month and year ends", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
  });
  it("moves a month and clamps to the last day when the target month is shorter", () => {
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2026-03-31", -1)).toBe("2026-02-28");
    expect(addMonths("2026-12-15", 1)).toBe("2027-01-15");
    expect(addMonths("2026-01-15", -1)).toBe("2025-12-15");
  });
  it("knows a leap February", () => {
    expect(daysInMonth(2028, 2)).toBe(29);
    expect(daysInMonth(2026, 2)).toBe(28);
  });
  it("runs the week Monday-first", () => {
    expect(weekdayIndex({ y: 2026, m: 10, d: 26 })).toBe(0); // a Monday
    expect(weekdayIndex({ y: 2026, m: 10, d: 25 })).toBe(6); // a Sunday
  });
});

describe("monthRows", () => {
  it("lays October 2026 out in whole weeks with blanks around it", () => {
    const rows = monthRows(2026, 10);
    expect(rows.every((r) => r.length === 7)).toBe(true);
    // The 1st is a Thursday: three blanks, then the 1st.
    expect(rows[0]).toEqual([null, null, null, "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]);
    expect(rows.flat().filter(Boolean)).toHaveLength(31);
  });
});

describe("labels", () => {
  it("writes a day short and long, read as written in any zone", () => {
    expect(shortDay("2026-10-28")).toBe("Oct 28, 2026");
    expect(longDay("2026-10-28")).toBe("Wednesday, October 28, 2026");
    expect(shortDay("junk")).toBe("");
  });
});
