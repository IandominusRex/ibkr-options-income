import { describe, expect, it } from "vitest";
import { bookWord, executionTitle, lastWindow, sourceWord, spreadOrderTitle, windowLabel } from "./fills";

const exec = (over: Record<string, unknown> = {}) =>
  ({ quantity: -1, underlying: "NVDA", sec_type: "OPT", right: "P", strike: 165, expiry: "2026-11-20", ...over }) as never;

describe("executionTitle", () => {
  it("says sold or bought by the sign of the quantity, with the contract", () => {
    expect(executionTitle(exec())).toBe("Sold 1 NVDA $165 put · Nov 20");
    expect(executionTitle(exec({ quantity: 2, right: "C", strike: 72.5 }))).toBe("Bought 2 NVDA $72.5 call · Nov 20");
  });
  it("names shares as shares", () => {
    expect(executionTitle(exec({ sec_type: "STK", right: null, strike: null, expiry: null, quantity: 100 }))).toBe(
      "Bought 100 NVDA shares",
    );
  });
  it("says what it does not know about an option", () => {
    expect(executionTitle(exec({ strike: null, expiry: null }))).toBe("Sold 1 NVDA strike n/a put");
  });
});

describe("words", () => {
  it("names the books and the sources in words", () => {
    expect(bookWord("system")).toBe("System");
    expect(bookWord("spreads")).toBe("Spreads");
    expect(bookWord("manual")).toBe("Manual");
    expect(bookWord("other")).toBe("other");
    expect(sourceWord("live")).toBe("live feed");
    expect(sourceWord("flex")).toBe("Flex query");
    expect(sourceWord("csv")).toBe("statement import");
    expect(sourceWord("odd")).toBe("odd");
  });
  it("labels the windows as chips and as sentences", () => {
    expect(windowLabel(7)).toBe("7 days");
    expect(windowLabel(365)).toBe("A year");
    expect(lastWindow(30)).toBe("the last 30 days");
    expect(lastWindow(365)).toBe("the last year");
  });
  it("titles a spread order by its strikes, or says the strikes are unknown", () => {
    const o = { short_strike: 763, long_strike: 758, side: "put" } as never;
    expect(spreadOrderTitle(o, "SPY")).toBe("SPY 763/758 put spread");
    expect(spreadOrderTitle({ short_strike: null, long_strike: null, side: null } as never, "SPY")).toBe(
      "SPY credit spread, strikes n/a",
    );
  });
});
