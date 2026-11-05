import { describe, expect, it } from "vitest";
import { countByAction, timeLabel, tradeEyebrow, tradeSentence, tradeStub, tradeTitle } from "./trades";
import type { DayTrade } from "./types";

function trade(over: Partial<DayTrade> = {}): DayTrade {
  return {
    key: "c1:opened",
    action: "opened",
    how: null,
    kind: "csp",
    source: "wheel",
    underlying: "AAPL",
    right: "P",
    strike: 180,
    long_strike: null,
    expiry: "2026-11-21",
    contracts: 1,
    at: "2026-10-15T14:42:00Z",
    is_live: false,
    premium: 235,
    bought_back: null,
    commissions: 1.3,
    commissions_complete: true,
    net_pnl: null,
    capital: 18000,
    roc_pct: 1.3056,
    annualized_pct: 12.2,
    pct_kept: null,
    dte_at_open: 39,
    days_held: null,
    reason: null,
    facts: [],
    approval_id: 7,
    review: null,
    rolled_to: null,
    ...over,
  };
}

const closed = (over: Partial<DayTrade> = {}) =>
  trade({
    key: "c1:closed",
    action: "closed",
    how: "bought_back",
    premium: 235,
    bought_back: 62,
    commissions: 2.6,
    net_pnl: 170.4,
    reason: "Closed for a profit: the position reached its profit target.",
    ...over,
  });

describe("tradeEyebrow", () => {
  it("names the action in words, then the kind of trade", () => {
    expect(tradeEyebrow(trade())).toBe("Opened · Cash-secured put");
    expect(tradeEyebrow(closed({ kind: "cc", right: "C" }))).toBe("Closed · Covered call");
    expect(tradeEyebrow(trade({ action: "rolled", how: "rolled", kind: "cc" }))).toBe("Rolled · Covered call");
    expect(tradeEyebrow(trade({ kind: "spread", source: "spreads" }))).toBe("Opened · Credit spread");
  });
});

describe("tradeTitle", () => {
  it("states what happened to which contract", () => {
    expect(tradeTitle(trade())).toBe("AAPL · Sold $180 put");
    expect(tradeTitle(closed())).toBe("AAPL · Bought back $180 put");
    expect(tradeTitle(closed({ how: "expired" }))).toBe("AAPL · $180 put expired");
    expect(tradeTitle(closed({ how: "assigned" }))).toBe("AAPL · $180 put assigned");
    expect(tradeTitle(closed({ how: "called_away", right: "C", strike: 72, underlying: "KO" }))).toBe(
      "KO · $72 call called away",
    );
  });
  it("names both strikes of a roll when the new leg is known", () => {
    const rolled = trade({
      action: "rolled",
      how: "rolled",
      kind: "cc",
      right: "C",
      underlying: "NVDA",
      strike: 160,
      rolled_to: { candidate_id: "n", strike: 165, expiry: "2026-11-20", contracts: 1, premium: 280, commissions: 1 },
    });
    expect(tradeTitle(rolled)).toBe("NVDA · Rolled $160 call to $165");
    expect(tradeTitle({ ...rolled, rolled_to: null })).toBe("NVDA · Rolled $160 call");
  });
  it("names a spread by both strikes", () => {
    const s = trade({ kind: "spread", source: "spreads", underlying: "SPY", strike: 580, long_strike: 575 });
    expect(tradeTitle(s)).toBe("SPY · Sold 580/575 put spread");
    expect(tradeTitle({ ...s, action: "closed", how: "bought_back" })).toBe("SPY · Closed 580/575 put spread");
    expect(tradeTitle({ ...s, action: "closed", how: "expired" })).toBe("SPY · 580/575 put spread expired");
  });
});

describe("tradeSentence", () => {
  it("opened: the credit and the consequence, in the proposal card's words", () => {
    expect(tradeSentence(trade())).toBe(
      "You collected $235.00. If AAPL closes under $180 on Nov 21, you buy 100 shares at $180.",
    );
    expect(tradeSentence(trade({ kind: "cc", right: "C", strike: 72, underlying: "KO", premium: 64, contracts: 2, expiry: "2026-11-14" }))).toBe(
      "You collected $64.00. If KO closes over $72 on Nov 14, your 200 shares are sold at $72.",
    );
  });
  it("opened spread: the most it can lose", () => {
    const s = trade({ kind: "spread", source: "spreads", underlying: "SPY", premium: 168, capital: 832 });
    expect(tradeSentence(s)).toBe("You collected $168.00. The most you can lose is $832.00.");
  });
  it("an unknown premium is said, not zeroed", () => {
    expect(tradeSentence(trade({ premium: null }))).toMatch(/^Premium not recorded\./);
  });
  it("closed and rolled: the stored reason, verbatim", () => {
    expect(tradeSentence(closed())).toBe("Closed for a profit: the position reached its profit target.");
    expect(tradeSentence(closed({ reason: null }))).toBe("Closed.");
  });
});

describe("tradeStub", () => {
  it("opened: premium, commission, return on what is held, and a year", () => {
    const lines = tradeStub(trade());
    expect(lines.map((l) => l.label)).toEqual(["Premium", "Commission", "On $18,000.00 held", "A year"]);
    expect(lines.map((l) => l.value)).toEqual([235, -1.3, 1.3056, 12.2]);
    expect(lines[3].total).toBe(true);
    expect(lines[2].format).toBe("percent");
  });
  it("opened: a call is held at its strike, a spread is at risk", () => {
    expect(tradeStub(trade({ kind: "cc", right: "C", capital: 7200 }))[2].label).toBe("On $7,200.00 of shares at the strike");
    expect(tradeStub(trade({ kind: "spread", capital: 832 }))[2].label).toBe("On $832.00 at risk");
    expect(tradeStub(trade({ capital: null, roc_pct: null }))[2]).toMatchObject({ label: "Return", value: null });
  });
  it("closed: the whole trade, and the lines sum to the net", () => {
    const lines = tradeStub(closed());
    expect(lines.map((l) => l.label)).toEqual(["Premium collected", "Bought back", "Commissions", "Net P&L"]);
    const [premium, back, fees, net] = lines.map((l) => l.value as number);
    expect(premium + back + fees).toBeCloseTo(net, 6);
    expect(lines[3].total).toBe(true);
  });
  it("closed: an expiry buys nothing back, so Bought back is a real zero", () => {
    const lines = tradeStub(closed({ how: "expired", bought_back: 0, commissions: 0, net_pnl: 235 }));
    expect(lines[1].value).toBe(0);
    expect(lines[3].value).toBe(235);
  });
  it("a rolled trade's total is the net on that leg", () => {
    expect(tradeStub(closed({ action: "rolled", how: "rolled" }))[3].label).toBe("Net on this leg");
  });
  it("unknowns stay null, never 0", () => {
    const lines = tradeStub(closed({ net_pnl: null, bought_back: null }));
    expect(lines[1].value).toBeNull();
    expect(lines[3].value).toBeNull();
  });
  it("incomplete commissions are said in the label", () => {
    expect(tradeStub(closed({ commissions_complete: false }))[2].label).toBe("Commissions (incomplete)");
    expect(tradeStub(trade({ commissions_complete: false }))[1].label).toBe("Commission (incomplete)");
  });
});

describe("timeLabel", () => {
  it("shows the fill in New York time", () => {
    expect(timeLabel(trade({ at: "2026-10-15T14:42:00Z" }))).toBe("10:42 AM ET");
  });
  it("an expiry settles at the close, so it says so instead of a time", () => {
    expect(timeLabel(closed({ how: "expired", at: "2026-10-15T20:00:00Z" }))).toBe("At expiry");
    expect(timeLabel(closed({ how: "assigned" }))).toBe("At expiry");
  });
});

describe("countByAction", () => {
  it("counts each action", () => {
    expect(countByAction([trade(), closed(), closed(), trade({ action: "rolled" })])).toEqual({
      opened: 1,
      closed: 2,
      rolled: 1,
    });
  });
});

// A value fill is a share trade in the option card's shape: `strike` is the fill price,
// `contracts` the share count and `expiry` the fill's date (src/reporting/day.py _value_trade).
describe("a value-book trade", () => {
  const bought = (over: Partial<DayTrade> = {}) =>
    trade({
      key: "value:7:buy:20261015T144200",
      action: "opened",
      kind: "value",
      source: "value",
      right: null,
      underlying: "GOOGL",
      strike: 180.5,
      expiry: "2026-10-15",
      contracts: 10,
      premium: null,
      commissions: null,
      capital: 1805,
      approval_id: null,
      reason: "Bought 10 GOOGL at $180.50: scaling in, tranche 1.",
      ...over,
    });
  const sold = (over: Partial<DayTrade> = {}) =>
    bought({
      key: "value:8:sell:20261015T150000",
      action: "closed",
      contracts: 5,
      strike: 190,
      capital: null,
      net_pnl: 47.5,
      reason: "Sold 5 GOOGL at $190.00: the stop was hit.",
      ...over,
    });

  it("is titled by what happened to the shares", () => {
    expect(tradeTitle(bought())).toBe("Bought 10 GOOGL");
    expect(tradeTitle(sold())).toBe("Sold 5 GOOGL");
  });
  it("is eyed as the value book, with the verb, not as an option", () => {
    expect(tradeEyebrow(bought())).toBe("Bought · Value book");
    expect(tradeEyebrow(sold())).toBe("Sold · Value book");
  });
  it("says it in the system's own sentence, and falls back to the fill when none was stored", () => {
    expect(tradeSentence(bought())).toBe("Bought 10 GOOGL at $180.50: scaling in, tranche 1.");
    expect(tradeSentence(sold({ reason: null }))).toBe("Sold 5 GOOGL at $190.00.");
  });
  it("sums a buy as the price and the cost, with no premium or commission line", () => {
    const lines = tradeStub(bought());
    expect(lines.map((l) => l.label)).toEqual(["Price a share", "Cost"]);
    expect(lines[0].value).toBe(180.5);
    expect(lines[1]).toMatchObject({ value: 1805, total: true });
  });
  it("sums a sale as the price and the realised result, which stays unknown rather than 0", () => {
    expect(tradeStub(sold()).map((l) => l.label)).toEqual(["Price a share", "Realised P&L"]);
    expect(tradeStub(sold())[1]).toMatchObject({ value: 47.5, total: true });
    expect(tradeStub(sold({ net_pnl: null }))[1].value).toBeNull();
  });
  it("counts as opened when bought and closed when sold", () => {
    expect(countByAction([bought(), sold(), sold()])).toEqual({ opened: 1, closed: 2, rolled: 0 });
  });
});
