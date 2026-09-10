import { describe, expect, it } from "vitest";
import { formatMoneyCell, freshnessText, isStale } from "./money";

describe("formatMoneyCell", () => {
  it("renders null as unknown", () => {
    expect(formatMoneyCell(null)).toBe("n/a");
  });

  it("renders undefined as unknown", () => {
    expect(formatMoneyCell(undefined)).toBe("n/a");
  });

  it("renders NaN as unknown", () => {
    expect(formatMoneyCell(NaN)).toBe("n/a");
  });

  it("renders a genuine zero as $0, never $0.00", () => {
    expect(formatMoneyCell(0)).toBe("$0");
  });

  it("formats a positive value with comma grouping and cents", () => {
    expect(formatMoneyCell(1234.5)).toBe("$1,234.50");
  });

  it("formats a large value with full precision, not compact notation", () => {
    expect(formatMoneyCell(1234567.89)).toBe("$1,234,567.89");
  });

  it("formats a negative value with a leading minus sign", () => {
    expect(formatMoneyCell(-125.5)).toBe("-$125.50");
  });
});

describe("freshnessText", () => {
  it("states a recent age in words", () => {
    const when = new Date(Date.now() - 12 * 60 * 1000).toISOString();
    expect(freshnessText(when)).toMatch(/12m ago/);
  });

  it("renders null as not captured, not just now", () => {
    expect(freshnessText(null)).toBe("not captured");
  });

  it("renders undefined as not captured", () => {
    expect(freshnessText(undefined)).toBe("not captured");
  });
});

describe("isStale", () => {
  it("is false for a reading inside the fresh window", () => {
    const when = new Date(Date.now() - 12 * 60 * 1000).toISOString();
    expect(isStale(when, 30)).toBe(false);
  });

  it("is true for a reading older than the fresh window", () => {
    const when = new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString();
    expect(isStale(when, 30)).toBe(true);
  });

  it("is true when there is no timestamp at all", () => {
    expect(isStale(null, 30)).toBe(true);
    expect(isStale(undefined, 30)).toBe(true);
  });
});
