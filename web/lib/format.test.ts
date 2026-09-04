import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatMoney, formatPeriod, relativeAge } from "./format";

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

describe("relativeAge", () => {
  const NOW = new Date("2026-09-04T12:00:00Z");

  beforeEach(() => vi.useFakeTimers().setSystemTime(NOW));
  afterEach(() => vi.useRealTimers());

  it("renders an empty string for a missing timestamp", () => {
    expect(relativeAge(null)).toBe("");
    expect(relativeAge(undefined)).toBe("");
  });

  it("renders an empty string for an unparseable timestamp", () => {
    expect(relativeAge("not a date")).toBe("");
  });

  it("renders minutes for a recent timestamp", () => {
    expect(relativeAge(new Date(NOW.getTime() - 5 * 60000).toISOString())).toBe("5m ago");
  });

  it("renders hours once past 60 minutes", () => {
    expect(relativeAge(new Date(NOW.getTime() - 3 * 3600000).toISOString())).toBe("3h ago");
  });

  it("renders days once past 24 hours", () => {
    expect(relativeAge(new Date(NOW.getTime() - 2 * 86400000).toISOString())).toBe("2d ago");
  });

  it("renders months once past 30 days", () => {
    expect(relativeAge(new Date(NOW.getTime() - 45 * 86400000).toISOString())).toBe("1mo ago");
  });
});