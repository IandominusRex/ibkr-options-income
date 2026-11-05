import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { TodayTrades } from "./TodayTrades";
import type { DayTrade } from "./types";

afterEach(cleanup);

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
    expiry: "2099-11-21",
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

const opened = trade({
  review: {
    why_attractive: "IV rank 62, premium 18% above fair value.",
    risks: "Earnings Oct 30 sit inside the window.",
    tradeoffs: "",
    assignment_considerations: "",
    rolling_considerations: "Roll down and out if challenged.",
    recommendation: "sell",
    priority: 1,
    confidence: 0.7,
    summary: "A sound put.",
    evidence: [],
  },
});
const closedTrade = trade({
  key: "c2:closed",
  action: "closed",
  how: "bought_back",
  underlying: "KO",
  strike: 68,
  premium: 235,
  bought_back: 62,
  commissions: 2.6,
  net_pnl: 170.4,
  reason: "Closed for a profit: the position reached its profit target.",
  facts: [
    { label: "Rule", text: "The system buys a short back once enough of its premium is kept.", source: "system" },
    { label: "Result", text: "Sold at $2.35 a share, bought back at $0.62. 74% of the premium kept.", source: "system" },
  ],
  approval_id: 8,
});
const rolled = trade({
  key: "c3:rolled",
  action: "rolled",
  how: "rolled",
  kind: "cc",
  right: "C",
  underlying: "NVDA",
  strike: 160,
  premium: 250,
  bought_back: 310,
  commissions: 2,
  net_pnl: -62,
  reason: "Rolled to the $165 call expiring Nov 20.",
  rolled_to: { candidate_id: "n", strike: 165, expiry: "2026-11-20", contracts: 1, premium: 280, commissions: 1 },
  facts: [
    { label: "Why it was rolled", text: "Trigger: strike breached. Roll up and out for a $0.30/sh net credit.", source: "system" },
    { label: "Claude's view", text: "Recommended: roll.", source: "claude" },
  ],
});

const day = (trades: DayTrade[], over: object = {}) => ({
  as_of: "",
  date: "2026-10-15",
  book: "paper",
  strategy: "all",
  trades,
  spreads_available: true,
  ...over,
});

describe("TodayTrades", () => {
  it("lists the day's cards with the count in the heading", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([opened, closedTrade, rolled]) });
    expect(await screen.findByRole("heading", { name: "Done today · 3 trades" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AAPL · Sold $180 put" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "KO · Bought back $68 put" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "NVDA · Rolled $160 call to $165" })).toBeInTheDocument();
  });

  it("filters by what happened and counts each pill", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([opened, closedTrade, rolled]) });
    const pills = await screen.findByRole("group", { name: "Trade type" });
    expect(within(pills).getByRole("button", { name: /^All\s*3$/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(pills).getByRole("button", { name: /^Opened\s*1$/ })).toBeInTheDocument();
    fireEvent.click(within(pills).getByRole("button", { name: /^Closed/ }));
    expect(screen.getByRole("heading", { name: "KO · Bought back $68 put" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "AAPL · Sold $180 put" })).toBeNull();
    fireEvent.click(within(pills).getByRole("button", { name: /^Rolled/ }));
    expect(screen.getByRole("heading", { name: /NVDA/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /KO/ })).toBeNull();
  });

  it("says so when a pill has nothing, instead of showing an empty frame", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([opened]) });
    const pills = await screen.findByRole("group", { name: "Trade type" });
    fireEvent.click(within(pills).getByRole("button", { name: /^Rolled/ }));
    expect(screen.getByText("Nothing rolled today.")).toBeInTheDocument();
  });

  it("an opened card shows Claude's review above the stub, labelled as Claude's", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([opened]) });
    const why = await screen.findByRole("button", { name: /Why this trade/ });
    expect(why).toHaveTextContent("Claude's review");
    expect(why).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(why);
    expect(screen.getByText(/IV rank 62/)).toBeInTheDocument();
    const stub = screen.getByRole("group", { name: "AAPL opened math" });
    expect(why.compareDocumentPosition(stub) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(stub).getByText("+$235.00")).toBeInTheDocument();
    expect(within(stub).getByText("−$1.30")).toBeInTheDocument();
    expect(within(stub).getByText("On $18,000.00 held")).toBeInTheDocument();
  });

  it("a closed card states its reason and sums the whole trade", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([closedTrade]) });
    expect(await screen.findByText("Closed for a profit: the position reached its profit target.")).toBeInTheDocument();
    const stub = screen.getByRole("group", { name: "KO closed math" });
    expect(within(stub).getByText("+$235.00")).toBeInTheDocument();
    expect(within(stub).getByText("−$62.00")).toBeInTheDocument();
    expect(within(stub).getByText("−$2.60")).toBeInTheDocument();
    expect(within(stub).getByText("Net P&L")).toBeInTheDocument();
    expect(within(stub).getByText("+$170.40")).toBeInTheDocument();
    const why = screen.getByRole("button", { name: /Why it closed/ });
    expect(why).toHaveTextContent("the system's rules");
    fireEvent.click(why);
    expect(screen.getByText(/74% of the premium kept/)).toBeInTheDocument();
  });

  it("a rolled card gives the trigger, the terms and Claude's view as Claude's, never as a rule", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([rolled]) });
    const why = await screen.findByRole("button", { name: /Why it was rolled/ });
    expect(why).toHaveTextContent("the system's rules and Claude's view");
    fireEvent.click(why);
    expect(screen.getByText(/Trigger: strike breached/)).toBeInTheDocument();
    expect(screen.getByText("Claude's view:")).toBeInTheDocument();
    expect(screen.getByText("Net on this leg")).toBeInTheDocument();
    expect(screen.getByText("−$62.00", { selector: "span" })).toBeInTheDocument();
  });

  it("links a trade that has an approval to its detail page, and no other", async () => {
    const spread = trade({ key: "s:opened", kind: "spread", source: "spreads", underlying: "SPY", strike: 580, long_strike: 575, approval_id: null, capital: 832 });
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([opened, spread]) });
    await screen.findByRole("heading", { name: /SPY/ });
    const links = screen.getAllByRole("link", { name: "Details" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/trades/7");
  });

  it("asks the API for the page's strategy", async () => {
    renderWithQuery(<TodayTrades strategy="cc" />, { "/pnl/day": day([]) });
    await screen.findByText("Nothing has traded yet today.");
    expect(apiFetchMock.mock.calls.some((c) => c[0] === "/pnl/day?strategy=cc")).toBe(true);
  });

  it("holds its place while loading and says so when the API is down", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, {});
    expect(await screen.findByText("Today's trades are unavailable right now.")).toBeInTheDocument();
  });

  it("says when spreads could not be read, so a quiet day is not mistaken for no spreads", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([opened], { spreads_available: false }) });
    expect(await screen.findByText(/Credit spreads are unavailable right now/)).toBeInTheDocument();
  });

  it("says who approved an opened trade, from the record", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([{ ...opened, decided_by: "system" }]) });
    expect(await screen.findByText("Approved by the system")).toBeInTheDocument();
  });

  it("says nothing about who approved it when that was not recorded", async () => {
    renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([{ ...opened, decided_by: null }]) });
    await screen.findByRole("article");
    expect(screen.queryByText(/^Approved/)).toBeNull();
  });
  describe("the value book", () => {
    const valueBuy = trade({
      key: "value:7:buy:20261015T144200",
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
      reason: "Bought 10 GOOGL at $180.50: Claude's verdict made it READY.",
      facts: [
        { label: "Rule", text: "Scaling in, tranche 1.", source: "system" },
        { label: "Claude's call", text: "Claude's value work called for this buy; Python's gates still applied.", source: "claude" },
      ],
    });
    const valueSale = trade({
      key: "value:8:sell:20261015T150000",
      action: "closed",
      kind: "value",
      source: "value",
      right: null,
      underlying: "GOOGL",
      strike: 190,
      expiry: "2026-10-15",
      contracts: 5,
      premium: null,
      commissions: null,
      capital: null,
      net_pnl: 47.5,
      approval_id: null,
      reason: "Sold 5 GOOGL at $190.00: the stop was hit.",
      facts: [{ label: "Rule", text: "The stop was hit.", source: "system" }],
    });

    it("lists a value fill as a trade card titled by what happened to the shares", async () => {
      renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([valueBuy, valueSale], { value_available: true }) });
      expect(await screen.findByRole("heading", { name: "Bought 10 GOOGL" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Sold 5 GOOGL" })).toBeInTheDocument();
      expect(screen.getByText("Bought · Value book")).toBeInTheDocument();
      expect(screen.getByText("Bought 10 GOOGL at $180.50: Claude's verdict made it READY.")).toBeInTheDocument();
    });
    it("labels Claude's cause as Claude's, apart from the rule", async () => {
      renderWithQuery(<TodayTrades strategy="value" />, { "/pnl/day": day([valueBuy], { strategy: "value", value_available: true }) });
      const why = await screen.findByRole("button", { name: /Why it was bought/ });
      expect(why).toHaveTextContent("the system's rules and Claude's view");
      fireEvent.click(why);
      expect(screen.getByText("Claude's call:")).toBeInTheDocument();
      expect(screen.getByText("Rule:")).toBeInTheDocument();
    });
    it("says a rule-only sale is the system's rules alone, and shows the realised result in its stub", async () => {
      renderWithQuery(<TodayTrades strategy="value" />, { "/pnl/day": day([valueSale], { strategy: "value", value_available: true }) });
      const why = await screen.findByRole("button", { name: /Why it was sold/ });
      expect(why).toHaveTextContent("the system's rules");
      expect(why).not.toHaveTextContent("Claude");
      const stub = screen.getByRole("group", { name: "GOOGL closed math" });
      expect(within(stub).getByText("Realised P&L")).toBeInTheDocument();
      expect(within(stub).getByText("+$47.50")).toBeInTheDocument();
    });
    it("has no Details link, since a value fill has no approval", async () => {
      renderWithQuery(<TodayTrades strategy="value" />, { "/pnl/day": day([valueBuy], { strategy: "value" }) });
      await screen.findByRole("heading", { name: "Bought 10 GOOGL" });
      expect(screen.queryByRole("link", { name: "Details" })).toBeNull();
    });
    it("asks for the value strategy", async () => {
      renderWithQuery(<TodayTrades strategy="value" />, { "/pnl/day": day([], { strategy: "value", value_available: true }) });
      await screen.findByText("Nothing has traded yet today.");
      expect(apiFetchMock.mock.calls.some((c) => c[0] === "/pnl/day?strategy=value")).toBe(true);
    });
    it("says the book could not be read under Value, never that nothing traded", async () => {
      renderWithQuery(<TodayTrades strategy="value" />, { "/pnl/day": day([], { strategy: "value", value_available: false }) });
      expect(await screen.findByText("The value book could not be read, so its trades are not listed.")).toBeInTheDocument();
      expect(screen.queryByText("Nothing has traded yet today.")).toBeNull();
    });
    it("notes the unread book under All without hiding the option trades", async () => {
      renderWithQuery(<TodayTrades strategy="all" />, { "/pnl/day": day([opened], { value_available: false }) });
      expect(await screen.findByText("The value book could not be read, so its trades are not listed.")).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "AAPL · Sold $180 put" })).toBeInTheDocument();
    });
    it("does not say the book could not be read when it is off and has never written", async () => {
      renderWithQuery(<TodayTrades strategy="all" />, {
        "/pnl/day": day([opened], { value_available: false }),
        "/value/book": { as_of: "", available: false, enabled: false, positions: [], proposals: [], funding: [], release_max_closes: 2, drain_healthy: true, drain_last_seen: null },
      });
      expect(await screen.findByRole("heading", { name: "AAPL · Sold $180 put" })).toBeInTheDocument();
      await new Promise((r) => setTimeout(r, 20));
      expect(screen.queryByText("The value book could not be read, so its trades are not listed.")).toBeNull();
    });
    it("stays quiet about the value book for a wheel strategy", async () => {
      renderWithQuery(<TodayTrades strategy="cc" />, { "/pnl/day": day([], { strategy: "cc", value_available: false }) });
      await screen.findByText("Nothing has traded yet today.");
      expect(screen.queryByText(/value book/i)).toBeNull();
    });
  });
});
