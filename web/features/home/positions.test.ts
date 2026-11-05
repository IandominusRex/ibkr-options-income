import { describe, expect, it } from "vitest";
import { buildPositionRows, buildValueRows, matchesQuery, optionSlug } from "./positions";

const TODAY = "2026-10-13";

const optionLeg = (over: Record<string, unknown> = {}) => ({
  as_of: "",
  symbol: "AMD 261024P00150000",
  right: "P",
  strike: 150,
  expiry: "2026-10-24",
  dte: 11,
  contracts: 1,
  short: true,
  delta: -0.4,
  delta_source: "ibkr",
  market_price: 3.1,
  market_value: -310,
  unrealized_pnl: -212,
  moneyness: "itm",
  assignment_risk: true,
  ...over,
});

const group = (underlying: string, options: unknown[], stock: unknown = null) => ({
  as_of: "",
  underlying,
  stock,
  options,
});

describe("buildPositionRows", () => {
  it("names a short put a CSP and flags assignment risk in words", () => {
    const [row] = buildPositionRows([group("AMD", [optionLeg()])] as never, [], TODAY);
    expect(row.kind).toBe("csp");
    expect(row.title).toBe("AMD $150 put");
    expect(row.status).toEqual({ word: "Assignment likely", tone: "flag" });
    expect(row.value).toBe(-212);
    expect(row.valueLabel).toBe("open P&L");
  });
  it("says Expires today on expiry day, ahead of any other status", () => {
    const [row] = buildPositionRows(
      [group("MSFT", [optionLeg({ right: "C", strike: 430, dte: 0, expiry: TODAY, assignment_risk: true })])] as never,
      [],
      TODAY,
    );
    expect(row.kind).toBe("cc");
    expect(row.status).toEqual({ word: "Expires today", tone: "today" });
  });
  it("states moneyness only when it is known", () => {
    const rows = buildPositionRows(
      [
        group("KO", [optionLeg({ moneyness: "otm", assignment_risk: false })]),
        group("PEP", [optionLeg({ moneyness: null, assignment_risk: false })]),
      ] as never,
      [],
      TODAY,
    );
    expect(rows.find((r) => r.title.startsWith("KO"))!.status).toEqual({ word: "Out of the money", tone: "neutral" });
    expect(rows.find((r) => r.title.startsWith("PEP"))!.status).toBeNull();
  });
  it("notes a covered call's cover only when the shares are really held", () => {
    const stock = { as_of: "", shares: 100, avg_cost: 60, adjusted_cost_basis: null, market_price: 70, market_value: 7000, unrealized_pnl: 1000, unrealized_pnl_adjusted: null };
    const rows = buildPositionRows([group("KO", [optionLeg({ right: "C", strike: 72 })], stock)] as never, [], TODAY);
    expect(rows.find((r) => r.kind === "cc")!.sub).toContain("covered by 100 shares");
    expect(rows.find((r) => r.kind === "shares")!.title).toBe("KO · 100 shares");
  });
  it("keeps an unknown P&L unknown", () => {
    const [row] = buildPositionRows([group("AMD", [optionLeg({ unrealized_pnl: null })])] as never, [], TODAY);
    expect(row.value).toBeNull();
  });
  it("adds spreads with what they were sold for", () => {
    const rows = buildPositionRows([], [
      { spread_id: "s1", mode: "paper", side: "put", expiry: TODAY, short_strike: 580, long_strike: 575, width: 5, contracts_opened: 1, contracts: 1, entry_credit: 0.42, entry_commission: 1.3, opened_at: "", status: "open", exit_debit: null, realized_pnl_usd: null },
    ] as never, TODAY, "SPY");
    expect(rows[0]).toMatchObject({ kind: "spread", title: "SPY 580/575 put spread", value: 42, valueLabel: "sold for" });
    expect(rows[0].status).toEqual({ word: "Expires today", tone: "today" });
  });
  it("sorts by expiry, shares last", () => {
    const stock = { as_of: "", shares: 100, avg_cost: 60, adjusted_cost_basis: null, market_price: 70, market_value: 7000, unrealized_pnl: 1000, unrealized_pnl_adjusted: null };
    const rows = buildPositionRows(
      [group("A", [optionLeg({ expiry: "2026-11-21" })], stock), group("B", [optionLeg({ expiry: "2026-10-24" })])] as never,
      [],
      TODAY,
    );
    expect(rows.map((r) => r.kind)).toEqual(["csp", "csp", "shares"]);
    expect(rows[0].title.startsWith("B")).toBe(true);
  });
  it("does not invent a strike or a right the API left out", () => {
    const [row] = buildPositionRows(
      [group("AMD", [optionLeg({ strike: null, right: null })])] as never,
      [],
      TODAY,
    );
    expect(row.kind).toBe("other");
    expect(row.title).toBe("AMD strike n/a option");
  });
});

describe("the page behind a row", () => {
  it("links an option to its contract's page by expiry, right and strike", () => {
    const [row] = buildPositionRows([group("AMD", [optionLeg()])] as never, [], TODAY);
    expect(row.underlying).toBe("AMD");
    expect(row.href).toBe("/positions/AMD/2026-10-24_P150");
    expect(optionSlug("2026-11-21", "C", 62.5)).toBe("2026-11-21_C62.5");
  });
  it("links shares and spreads", () => {
    const stock = { as_of: "", shares: 100, avg_cost: 60, adjusted_cost_basis: null, market_price: 70, market_value: 7000, unrealized_pnl: 1000, unrealized_pnl_adjusted: null };
    const rows = buildPositionRows(
      [group("KO", [], stock)] as never,
      [{ spread_id: "s1", side: "put", expiry: TODAY, short_strike: 580, long_strike: 575, width: 5, contracts_opened: 1, contracts: 1, entry_credit: 0.42, status: "open" }] as never,
      TODAY,
      "SPY",
    );
    expect(rows.find((r) => r.kind === "shares")!.href).toBe("/positions/KO/shares");
    expect(rows.find((r) => r.kind === "spread")!.href).toBe("/positions/SPY/spread-s1");
  });
  it("does not link a contract whose strike or right the API left out", () => {
    const [row] = buildPositionRows([group("AMD", [optionLeg({ strike: null })])] as never, [], TODAY);
    expect(row.href).toBeNull();
  });
});

describe("matchesQuery", () => {
  const rows = buildPositionRows(
    [
      group("AMZN", [optionLeg({ symbol: "a", strike: 250 })]),
      group("NVDA", [optionLeg({ symbol: "b", strike: 165, right: "C" })]),
      group("AMD", [optionLeg({ symbol: "c", strike: 150 })]),
    ] as never,
    [],
    TODAY,
  );
  const names = (q: string) => rows.filter((r) => matchesQuery(r, q)).map((r) => r.underlying);
  it("matches a ticker in any case, by prefix or inside", () => {
    expect(names("amzn")).toEqual(["AMZN"]);
    expect(names("AM")).toEqual(["AMD", "AMZN"]);
    expect(names("vd")).toEqual(["NVDA"]);
  });
  it("matches the contract's own words and strike", () => {
    expect(names("call")).toEqual(["NVDA"]);
    expect(names("150")).toEqual(["AMD"]);
    expect(names("amd put")).toEqual(["AMD"]);
    expect(names("amd call")).toEqual([]);
  });
  it("commas ask for several names", () => {
    expect(names("amzn, nvda")).toEqual(["AMZN", "NVDA"]);
  });
  it("does not match the sub-line, so a weekday is not a ticker", () => {
    expect(names("sat")).toEqual([]);
  });
  it("an empty search matches everything", () => {
    expect(names("")).toHaveLength(3);
    expect(names("  ,  ")).toHaveLength(3);
  });
});

describe("buildValueRows", () => {
  const vp = (over: Record<string, unknown> = {}) => ({
    id: 1, symbol: "AAPL", list_name: "deep_value", status: "open" as const, shares: 10, avg_cost: 170, mark: 180,
    next_exit: { kind: "stop" as const, level: 150 }, ...over,
  });
  it("builds one value row a position with the open P&L worked from the mark and the average cost", () => {
    const [row] = buildValueRows([vp()]);
    expect(row).toMatchObject({ kind: "value", underlying: "AAPL", title: "AAPL · 10 shares", value: 100, valueLabel: "open P&L", href: null });
    expect(row.sub).toBe("Deep value · average cost $170.00 · next exit: stop at $150.00");
    expect(row.status).toBeNull();
  });
  it("leaves out a closed position and leaves the P&L unknown when the cost or the mark is", () => {
    const rows = buildValueRows([vp({ id: 1, status: "closed" }), vp({ id: 2, mark: null })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].value).toBeNull();
  });
  it("keeps the wheel's share row on the same name as a separate row", () => {
    const wheel = buildPositionRows(
      [
        group("AAPL", [], {
          as_of: "", shares: 100, avg_cost: 150, adjusted_cost_basis: null, market_price: null, market_value: null,
          unrealized_pnl: 10, unrealized_pnl_adjusted: null,
        }),
      ] as never,
      [],
      TODAY,
    );
    const book = buildValueRows([vp()]);
    expect(wheel.map((r) => r.key)).toEqual(["AAPL:stock"]);
    expect(book.map((r) => r.key)).toEqual(["value:1"]);
    expect(wheel[0].title).toBe("AAPL · 100 shares");
    expect(book[0].title).toBe("AAPL · 10 shares");
  });
});
