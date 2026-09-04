import { describe, expect, it } from "vitest";
import { formatMoney, formatPeriod } from "./format";

describe("formatMoney", () => {
  it("compacts billions", () => expect(formatMoney(391035000000)).toBe("$391.0B"));
  it("compacts millions", () => expect(formatMoney(1250000)).toBe("$1.3M"));
  it("handles negatives", () => expect(formatMoney(-4500000000)).toBe("-$4.5B"));
  it("renders an unknown as n/a, never as zero", () => expect(formatMoney(null)).toBe("n/a"));
  it("renders a real zero as a zero", () => expect(formatMoney(0)).toBe("$0"));
});

describe("formatPeriod", () => {
  it("renders an ISO date as a short period label", () =>
    expect(formatPeriod("2024-09-28")).toBe("Sep 2024"));
});