import { describe, expect, it } from "vitest";
import { cashPct, pctLabel, ringFraction } from "./donut";

describe("cashPct", () => {
  it("is cash over net liquidation", () => {
    expect(cashPct(40_000, 125_000)).toBeCloseTo(32);
  });
  it("is unknown when either figure is, never 0", () => {
    expect(cashPct(null, 125_000)).toBeNull();
    expect(cashPct(40_000, null)).toBeNull();
  });
  it("is unknown for an account that is not positive, which has no share to take", () => {
    expect(cashPct(10, 0)).toBeNull();
    expect(cashPct(10, -5)).toBeNull();
  });
  it("keeps a real zero and a real overdraft", () => {
    expect(cashPct(0, 100)).toBe(0);
    expect(cashPct(-20, 100)).toBe(-20);
  });
});

describe("ringFraction", () => {
  it("draws a percent as a share of the ring, capped at the full ring", () => {
    expect(ringFraction(25)).toBe(0.25);
    expect(ringFraction(140)).toBe(1);
  });
  it("draws nothing for unknown or negative", () => {
    expect(ringFraction(null)).toBe(0);
    expect(ringFraction(-10)).toBe(0);
  });
});

describe("pctLabel", () => {
  it("writes one decimal and a real minus", () => {
    expect(pctLabel(22.5)).toBe("22.5%");
    expect(pctLabel(-3.04)).toBe("−3.0%");
  });
  it("is null for unknown so the caller writes n/a", () => {
    expect(pctLabel(null)).toBeNull();
  });
});
