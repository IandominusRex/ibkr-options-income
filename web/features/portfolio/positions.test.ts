import { describe, expect, it } from "vitest";
import type { PositionGroupData } from "@/components/portfolio/types";
import type { SpreadPosition } from "@/features/home/types";
import {
  buildNameCards,
  countByFilter,
  legDetail,
  nameFigures,
  nameSummary,
  narrow,
  rowsPnl,
  spreadRows,
} from "./positions";

const TODAY = "2026-10-23";
const leg = (over: Record<string, unknown> = {}) => ({
  as_of: "", symbol: "x", right: "P", strike: 180, expiry: "2099-11-21", dte: 30, contracts: 1,
  short: true, delta: -0.21, delta_source: "ibkr", market_price: 1.42, market_value: -142,
  unrealized_pnl: 38, moneyness: "otm", assignment_risk: false, ...over,
});
const stock = (over: Record<string, unknown> = {}) => ({
  as_of: "", shares: 100, avg_cost: 182.4, adjusted_cost_basis: null, market_price: 190,
  market_value: 19000, unrealized_pnl: 760, unrealized_pnl_adjusted: null, ...over,
});
const group = (underlying: string, options: object[], stk: object | null = null) =>
  ({ as_of: "", underlying, stock: stk, options }) as unknown as PositionGroupData;
const spread = (over: Record<string, unknown> = {}) =>
  ({
    as_of: "", spread_id: "s1", mode: "paper", side: "put", expiry: "2099-11-21", short_strike: 763,
    long_strike: 758, width: 5, contracts_opened: 2, contracts: 2, entry_credit: 0.25,
    entry_commission: 2.6, opened_at: "", status: "open", exit_debit: null, exit_commission: null,
    exit_reason: null, closed_at: null, realized_pnl_usd: null, ...over,
  }) as unknown as SpreadPosition;

const pnl = (g: PositionGroupData) => rowsPnl(buildNameCards([g], TODAY)[0].rows);

describe("rowsPnl", () => {
  it("adds the rows up when every one is known", () => {
    expect(pnl(group("AAPL", [leg(), leg({ symbol: "y", right: "C", strike: 200, unrealized_pnl: -12 })]))).toBe(26);
  });
  it("is unknown when any row is unknown, never the sum of the rest", () => {
    expect(pnl(group("AAPL", [leg(), leg({ symbol: "y", unrealized_pnl: null })]))).toBeNull();
  });
  it("keeps a genuine zero", () => {
    expect(pnl(group("AAPL", [leg({ unrealized_pnl: 5 }), leg({ symbol: "y", unrealized_pnl: -5 })]))).toBe(0);
  });
  it("is unknown for no rows", () => {
    expect(rowsPnl([])).toBeNull();
  });
  it("adds the shares row as the card shows it, the premium-adjusted figure when there is one", () => {
    expect(pnl(group("AAPL", [leg()], stock({ unrealized_pnl_adjusted: 900 })))).toBe(938);
    expect(pnl(group("AAPL", [leg()], stock()))).toBe(798);
  });
});

describe("buildNameCards", () => {
  it("orders the names alphabetically and drops a group with nothing to show", () => {
    const cards = buildNameCards([group("KO", [leg()]), group("AAPL", [leg()]), group("EMPTY", [])], TODAY);
    expect(cards.map((c) => c.underlying)).toEqual(["AAPL", "KO"]);
  });
  it("keys each option's figure line by the row's own key", () => {
    const [card] = buildNameCards([group("AAPL", [leg()])], TODAY);
    expect(Object.keys(card.details)).toEqual(["AAPL:x"]);
    expect(card.rows[0].key).toBe("AAPL:x");
  });
  it("flags a roll alert on the contract the monitor raised it on", () => {
    const [card] = buildNameCards([group("AAPL", [leg()])], TODAY, new Set(["x"]));
    expect(card.rows[0].alert).toBe(true);
  });
});

describe("legDetail", () => {
  it("writes delta with its source, the mark and the value", () => {
    expect(legDetail(leg() as never)).toEqual([
      { label: "delta", value: "-0.21 (ibkr)" },
      { label: "mark", value: "$1.42" },
      { label: "value", value: "-$142.00" },
    ]);
  });
  it("leaves an unknown figure null, never 0", () => {
    const parts = legDetail(leg({ delta: null, market_price: null, market_value: null }) as never);
    expect(parts.map((p) => p.value)).toEqual([null, null, null]);
  });
  it("shows a delta without a source", () => {
    expect(legDetail(leg({ delta_source: null }) as never)[0].value).toBe("-0.21");
  });
});

describe("narrow and countByFilter", () => {
  const cards = buildNameCards(
    [
      group("AAPL", [leg(), leg({ symbol: "y", right: "C", strike: 200 })], stock()),
      group("KO", [leg({ symbol: "z", right: "C", strike: 72 })]),
    ],
    TODAY,
  );
  it("keeps only the rows of the chosen type and drops a card left with none", () => {
    expect(narrow(cards, "cc", "").map((c) => [c.underlying, c.rows.length])).toEqual([["AAPL", 1], ["KO", 1]]);
    expect(narrow(cards, "csp", "").map((c) => c.underlying)).toEqual(["AAPL"]);
    expect(narrow(cards, "shares", "").map((c) => c.rows.length)).toEqual([1]);
  });
  it("searches the ticker and the contract's own words", () => {
    expect(narrow(cards, "all", "ko").map((c) => c.underlying)).toEqual(["KO"]);
    expect(narrow(cards, "all", "aapl call").map((c) => c.rows.map((r) => r.title))).toEqual([["AAPL $200 call"]]);
  });
  it("counts what each chip would show with the search applied, spreads included", () => {
    const spreads = spreadRows([spread()], TODAY, "SPY");
    expect(countByFilter(cards, spreads, "")).toEqual({ all: 5, csp: 1, cc: 2, spread: 1, shares: 1 });
    expect(countByFilter(cards, spreads, "aapl")).toEqual({ all: 3, csp: 1, cc: 1, spread: 0, shares: 1 });
  });
});

const priced = (g: PositionGroupData, price: Record<string, unknown>) => ({ ...g, ...price }) as unknown as PositionGroupData;
const labelled = (figs: { label: string; value: string | null }[]) => Object.fromEntries(figs.map((f) => [f.label, f.value]));

describe("a name card's price, summary and figures", () => {
  it("carries the price and where it came from", () => {
    const held = priced(group("HIMS", [leg()], stock()), { underlying_price: 28.42, underlying_price_basis: "position" });
    expect(buildNameCards([held], TODAY)[0].price).toEqual({ value: 28.42, basis: "position", date: null });
    const optionsOnly = priced(group("MSFT", [leg()]), {
      underlying_price: 400.5, underlying_price_basis: "close", underlying_price_date: "2026-10-27",
    });
    expect(buildNameCards([optionsOnly], TODAY)[0].price).toEqual({ value: 400.5, basis: "close", date: "2026-10-27" });
  });

  it("has no price when the API gave none, never 0", () => {
    expect(buildNameCards([group("ZZZ", [leg()])], TODAY)[0].price).toBeNull();
  });

  it("writes what the name is made of", () => {
    const [card] = buildNameCards([group("AAPL", [leg(), leg({ symbol: "y", right: "C", strike: 200 })], stock())], TODAY);
    expect(nameSummary(card)).toBe("100 shares · avg $182.40 · 1 cash-secured put · 1 covered call");
  });

  it("figures the shares' value and cost, the net delta in shares, the next expiry and the cash secured", () => {
    const [card] = buildNameCards([group("AAPL", [leg()], stock())], TODAY);
    const f = labelled(nameFigures(card));
    expect(f["Value"]).toBe("$19,000.00");
    expect(f["Cost basis"]).toBe("$18,240.00");
    // 100 shares, plus a short put at delta -0.21 which is +21 shares long.
    expect(f["Net delta"]).toBe("+121 sh");
    expect(f["Next expiry"]).toMatch(/Nov 21 · 30d$/);
    expect(f["Cash secured"]).toBe("$18,000.00");
  });

  it("measures against the premium-adjusted cost when there is one, as the P&L does", () => {
    const [card] = buildNameCards([group("AAPL", [], stock({ adjusted_cost_basis: 175 }))], TODAY);
    const f = labelled(nameFigures(card));
    expect(f["Adjusted cost"]).toBe("$17,500.00");
    expect(f["Cost basis"]).toBeUndefined();
  });

  it("makes the net delta unknown when any delta is, never the rest added up", () => {
    const [card] = buildNameCards([group("AAPL", [leg({ delta: null })], stock())], TODAY);
    expect(labelled(nameFigures(card))["Net delta"]).toBeNull();
  });

  it("leaves out the shares' figures when a type chip drops the shares row", () => {
    const cards = narrow(buildNameCards([group("AAPL", [leg()], stock())], TODAY), "csp", "");
    const f = labelled(nameFigures(cards[0]));
    expect(f["Value"]).toBeUndefined();
    expect(f["Net delta"]).toBe("+21 sh");
  });
});
