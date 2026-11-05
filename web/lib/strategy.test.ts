import { describe, expect, it } from "vitest";
import {
  STRATEGY_EYEBROW,
  STRATEGY_FILTERS,
  STRATEGY_LABEL,
  WHEEL_FILTERS,
  kindOf,
  matchesFilter,
  parseStrategyFilter,
} from "./strategy";

describe("kindOf", () => {
  it("maps the backend's strategy names", () => {
    expect(kindOf("cash_secured_put", "P")).toBe("csp");
    expect(kindOf("covered_call", "C")).toBe("cc");
    expect(kindOf("credit_spread", null)).toBe("spread");
  });
  it("files a roll under the side it rolls", () => {
    expect(kindOf("roll", "P")).toBe("csp");
    expect(kindOf("roll", "C")).toBe("cc");
    expect(kindOf("roll", null)).toBeNull();
  });
  it("returns null for anything it does not know", () => {
    expect(kindOf("iron_condor", "P")).toBeNull();
    expect(kindOf(undefined, undefined)).toBeNull();
  });
});

describe("parseStrategyFilter", () => {
  it("treats a junk or missing value as All", () => {
    expect(parseStrategyFilter("foo")).toBe("all");
    expect(parseStrategyFilter(null)).toBe("all");
  });
  it("keeps real values", () => {
    expect(parseStrategyFilter("csp")).toBe("csp");
    expect(parseStrategyFilter("spread")).toBe("spread");
  });
});

describe("matchesFilter", () => {
  it("All matches everything, even an unknown kind", () => {
    expect(matchesFilter(null, "all")).toBe(true);
    expect(matchesFilter("cc", "all")).toBe(true);
  });
  it("a specific filter matches only its kind", () => {
    expect(matchesFilter("cc", "csp")).toBe(false);
    expect(matchesFilter(null, "csp")).toBe(false);
    expect(matchesFilter("csp", "csp")).toBe(true);
  });
});

describe("the value kind", () => {
  it("is the last filter, labelled Value, with an eyebrow of its own", () => {
    expect(STRATEGY_FILTERS).toEqual(["all", "csp", "cc", "spread", "value"]);
    expect(STRATEGY_LABEL.value).toBe("Value");
    expect(STRATEGY_EYEBROW.value).toBe("Value book");
  });
  it("is read from the URL, and the wheel's own pages leave it out", () => {
    expect(parseStrategyFilter("value")).toBe("value");
    expect(WHEEL_FILTERS).toEqual(["all", "csp", "cc", "spread"]);
    expect(parseStrategyFilter("value", WHEEL_FILTERS)).toBe("all");
  });
  it("is never guessed from a wheel strategy name; only the value filter matches it", () => {
    expect(kindOf("value", null)).toBeNull();
    expect(matchesFilter(null, "value")).toBe(false);
    expect(matchesFilter("value", "value")).toBe(true);
    expect(matchesFilter("value", "csp")).toBe(false);
  });
});
