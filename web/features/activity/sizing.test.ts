import { describe, expect, it } from "vitest";
import { groupNote, groupSub, groupTitle, marks, rulesNote } from "./sizing";

const group = (over: Record<string, unknown> = {}) =>
  ({
    key: "scale_in_zone:never_sent", kind: "scale_in_zone", split: "never_sent", count: 2,
    contracts_withheld: 4, resolved: 1, exact: 0, pnl_expiry: 120, pnl_rules: 80, rules_missing: 0,
    applied: null, unapplied: null, ...over,
  }) as never;

describe("groupTitle", () => {
  it("names the kind and what became of the puts", () => {
    expect(groupTitle(group())).toBe("Scale-in ladder · never sent");
    expect(groupTitle(group({ kind: "regime_budget", split: "sent_smaller" }))).toBe("Regime budget · sent smaller");
    expect(groupTitle(group({ kind: "cc_breakout_floor", split: "pushed_out" }))).toBe("Breakout rule · pushed out");
  });
  it("puts Claude's cuts on one line", () => {
    expect(groupTitle(group({ kind: "claude_cut", split: "overrides" }))).toBe("Claude's size cut");
  });
});

describe("groupSub", () => {
  it("counts the actions, the valued ones and the contracts held back", () => {
    expect(groupSub(group())).toBe("2 actions · 1 valued so far · 4 contracts held back");
    expect(groupSub(group({ count: 1, resolved: 0, contracts_withheld: 1 }))).toBe(
      "1 action · 0 valued so far · 1 contract held back",
    );
  });
  it("says a pushed-out line is counted and not valued", () => {
    expect(groupSub(group({ split: "pushed_out", count: 3, resolved: null, contracts_withheld: null }))).toBe(
      "3 actions · counted, not valued",
    );
  });
});

describe("groupNote", () => {
  it("says how many cuts were applied and how many only recorded", () => {
    expect(groupNote(group({ split: "overrides", applied: 1, unapplied: 2 }))).toBe("1 applied, 2 recorded only.");
  });
  it("explains a pushed-out line", () => {
    expect(groupNote(group({ split: "pushed_out" }))).toBe(
      "A covered call was still sold on the name that day, so the breakout rule only pushed it out.",
    );
  });
  it("says how many valued rows were valued at the traded contracts' realised P&L", () => {
    expect(groupNote(group({ exact: 2, resolved: 3 }))).toBe(
      "2 of the valued rows are valued at the realised P&L of the contracts that did trade.",
    );
    expect(groupNote(group({ exact: 1, resolved: 1 }))).toBe(
      "1 of the valued rows is valued at the realised P&L of the contract that did trade.",
    );
  });
  it("says nothing when there is nothing to add", () => {
    expect(groupNote(group())).toBeNull();
  });
});

describe("marks", () => {
  it("gives both marks when rows are valued", () => {
    expect(marks(group())).toEqual({ expiry: 120, rules: 80 });
  });
  it("gives neither when nothing is valued yet, never zeros", () => {
    expect(marks(group({ resolved: 0, pnl_expiry: 0, pnl_rules: 0 }))).toEqual({ expiry: null, rules: null });
  });
  it("leaves the exit-rule mark out when no valued row has an entry IV", () => {
    expect(marks(group({ resolved: 2, rules_missing: 2 }))).toEqual({ expiry: 120, rules: null });
  });
  it("keeps the exit-rule mark when only some valued rows lack one", () => {
    expect(marks(group({ resolved: 3, rules_missing: 1 })).rules).toBe(80);
  });
  it("gives no marks to a pushed-out line", () => {
    expect(marks(group({ split: "pushed_out", resolved: null, pnl_expiry: null, pnl_rules: null }))).toEqual({
      expiry: null,
      rules: null,
    });
  });
});

describe("rulesNote", () => {
  it("says how many valued rows have no entry IV", () => {
    expect(rulesNote(group({ rules_missing: 2 }))).toBe("2 valued rows have no entry IV, so their exit-rule mark is left out.");
    expect(rulesNote(group({ rules_missing: 1 }))).toBe("1 valued row has no entry IV, so its exit-rule mark is left out.");
  });
  it("is null when none is missing", () => {
    expect(rulesNote(group())).toBeNull();
    expect(rulesNote(group({ rules_missing: null }))).toBeNull();
  });
});

describe("a guaranteed-lot line counts the lots the floor let through", () => {
  const floor = (over: Record<string, unknown> = {}) =>
    group({ key: "regime_floor_lot:sent_smaller", kind: "regime_floor_lot", split: "sent_smaller", ...over });

  it("says let through, not held back, in the counts", () => {
    expect(groupSub(floor({ count: 2, resolved: 2, contracts_withheld: 2 }))).toBe(
      "2 actions · 2 valued so far · 2 contracts let through",
    );
    expect(groupSub(floor({ count: 1, resolved: 1, contracts_withheld: 1 }))).toBe(
      "1 action · 1 valued so far · 1 contract let through",
    );
  });

  it("keeps held back for every other kind", () => {
    expect(groupSub(group({ kind: "regime_budget", split: "sent_smaller" }))).toContain("contracts held back");
  });

  it("says a positive number is what the guaranteed lots earned", () => {
    expect(groupNote(floor())).toBe("A positive number here is what the guaranteed lots earned: letting them through paid.");
  });

  it("keeps the exact-value note beside it", () => {
    expect(groupNote(floor({ exact: 1, resolved: 1 }))).toBe(
      "A positive number here is what the guaranteed lots earned: letting them through paid. 1 of the valued rows is valued at the realised P&L of the contract that did trade.",
    );
  });
});
