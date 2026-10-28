import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { PositionsView } from "./PositionsView";

const now = () => new Date().toISOString();
const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const leg = (over: Record<string, unknown> = {}) => ({
  as_of: "", symbol: "x", right: "P", strike: 180, expiry: "2099-11-21", dte: 30, contracts: 1,
  short: true, delta: -0.21, delta_source: "ibkr", market_price: 1.42, market_value: -142,
  unrealized_pnl: 38, moneyness: "otm", assignment_risk: false, ...over,
});
const stock = { as_of: "", shares: 100, avg_cost: 182.4, adjusted_cost_basis: null, market_price: 190, market_value: 19000, unrealized_pnl: 760, unrealized_pnl_adjusted: null };
const group = (underlying: string, options: unknown[], stk: unknown = null) => ({ as_of: "", underlying, stock: stk, options });
const positions = (groups: unknown[], over: Record<string, unknown> = {}) => ({ as_of: now(), source: "monitor", degraded: false, groups, ...over });
const spreadsOn = { as_of: "", available: true, underlying: "SPY", mode: "paper", positions: [] };
const common = {
  "/options/shorts": { as_of: "", shorts: [] },
  "/claude/context": { available: false, dossiers: [] },
};
const base = { ...common, "/spreads/positions": spreadsOn };
const aapl = group("AAPL", [leg(), leg({ symbol: "y", right: "C", strike: 200, unrealized_pnl: -12 })], stock);
const ko = group("KO", [leg({ symbol: "z", right: "C", strike: 72, unrealized_pnl: 30 })]);

describe("PositionsView", () => {
  it("groups the contracts under their ticker and totals the name's open P&L", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([aapl]) });
    expect(await screen.findByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    expect(screen.getByText("AAPL $180 put")).toBeInTheDocument();
    expect(screen.getByText("AAPL $200 call")).toBeInTheDocument();
    expect(screen.getByText("AAPL · 100 shares")).toBeInTheDocument();
    expect(screen.getByTestId("name-pnl")).toHaveTextContent("+$786.00");
  });

  it("puts the price at the card's top right with where it came from, and the figures under the open P&L", async () => {
    const held = { ...aapl, underlying_price: 190, underlying_price_basis: "position", underlying_price_date: null };
    const optionsOnly = {
      ...ko, underlying_price: 71.25, underlying_price_basis: "close", underlying_price_date: "2026-10-27",
    };
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([held, optionsOnly]) });
    const [aaplPrice, koPrice] = await screen.findAllByTestId("name-price");
    expect(aaplPrice).toHaveTextContent("$190.00");
    expect(aaplPrice).toHaveTextContent("Last price");
    expect(koPrice).toHaveTextContent("$71.25");
    expect(koPrice).toHaveTextContent("Close Oct 27");
    expect(screen.getByText("100 shares · avg $182.40 · 1 cash-secured put · 1 covered call")).toBeInTheDocument();
    const aaplCard = screen.getByRole("article", { name: /AAPL/ });
    expect(within(aaplCard).getByText("Value").nextSibling).toHaveTextContent("$19,000.00");
    expect(within(aaplCard).getByText("Cash secured").nextSibling).toHaveTextContent("$18,000.00");
  });

  it("says the price is n/a, hatched, when the API has none for a name", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([ko]) });
    const price = await screen.findByTestId("name-price");
    expect(within(price).getByText("n/a")).toHaveClass("hatch");
  });

  it("shows n/a for a name's total when one leg is unknown, never the sum of the rest", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/portfolio/positions": positions([group("AAPL", [leg(), leg({ symbol: "y", unrealized_pnl: null })])]),
    });
    const total = await screen.findByTestId("name-pnl");
    expect(within(total).getByText("n/a")).toHaveClass("hatch");
    expect(total).not.toHaveTextContent("38");
  });

  it("keeps a genuine zero as $0", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/portfolio/positions": positions([group("AAPL", [leg({ unrealized_pnl: 5 }), leg({ symbol: "y", unrealized_pnl: -5 })])]),
    });
    expect(await screen.findByTestId("name-pnl")).toHaveTextContent("$0");
  });

  it("puts the delta, the mark and the value under each contract, n/a where unknown", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/portfolio/positions": positions([group("AAPL", [leg({ delta: null })])]),
    });
    const link = await screen.findByRole("link", { name: /AAPL \$180 put/ });
    expect(link).toHaveTextContent("delta n/a · mark $1.42 · value -$142.00");
  });

  it("opens each contract's page from its row and marks a roll alert in words", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/options/shorts": { as_of: "", shorts: [{ position_symbol: "x", alerts: [{ id: 1 }] }] },
      "/portfolio/positions": positions([group("AAPL", [leg()])]),
    });
    const link = await screen.findByRole("link", { name: /AAPL \$180 put/ });
    expect(link).toHaveAttribute("href", "/positions/AAPL/2099-11-21_P180");
    expect(await screen.findByText("Roll alert")).toBeInTheDocument();
  });

  it("narrows by type and by search, and the chips count what each would show", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([aapl, ko]) });
    expect(await screen.findByRole("button", { name: "All 4" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "CCs 2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CCs 2" }));
    expect(screen.queryByText("AAPL $180 put")).toBeNull();
    expect(screen.getByText("KO $72 call")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "All 4" }));
    fireEvent.change(screen.getByLabelText("Search positions"), { target: { value: "ko" } });
    expect(screen.queryByRole("heading", { name: "AAPL" })).toBeNull();
    expect(screen.getByRole("button", { name: "All 1" })).toBeInTheDocument();
  });

  it("says nothing matches a search, in words", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([ko]) });
    await screen.findByText("KO $72 call");
    fireEvent.change(screen.getByLabelText("Search positions"), { target: { value: "zzz" } });
    expect(screen.getByText('No positions match "zzz".')).toBeInTheDocument();
  });

  it("adds a card for the open credit spreads", async () => {
    const spread = {
      as_of: "", spread_id: "s1", mode: "paper", side: "put", expiry: "2099-11-21", short_strike: 763,
      long_strike: 758, width: 5, contracts_opened: 2, contracts: 2, entry_credit: 0.25,
      entry_commission: 2.6, opened_at: "", status: "open", exit_debit: null, exit_commission: null,
      exit_reason: null, closed_at: null, realized_pnl_usd: null,
    };
    renderWithQuery(<PositionsView />, {
      ...base,
      "/spreads/positions": { ...spreadsOn, positions: [spread] },
      "/portfolio/positions": positions([ko]),
    });
    expect(await screen.findByRole("heading", { name: "SPY credit spreads" })).toBeInTheDocument();
    expect(screen.getByText("SPY 763/758 put spread")).toBeInTheDocument();
  });

  it("says an unreadable spreads book is unavailable, not empty", async () => {
    // No "/spreads/positions" answer: the request fails, which is not the same as an empty book.
    renderWithQuery(<PositionsView />, { ...common, "/portfolio/positions": positions([ko]) });
    await screen.findByText("KO $72 call");
    expect(await screen.findByText("Credit spreads are unavailable right now, so they are not listed.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Credit spreads" }));
    expect(screen.getByText("Credit spreads are unavailable right now.")).toBeInTheDocument();
    expect(screen.queryByText("No credit spreads open.")).toBeNull();
  });

  it("says Delayed and the age when the reading is old", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/portfolio/positions": positions([ko], { as_of: ago(3), source: "eod", degraded: true }),
    });
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
  });

  it("tells no snapshot apart from no positions", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([], { source: "none", degraded: true }) });
    expect(await screen.findByText("No portfolio snapshot has been captured yet.")).toBeInTheDocument();
    expect(screen.queryByText("No open positions.")).toBeNull();
  });

  it("says no positions are open when the reading is real and empty", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([]) });
    expect(await screen.findByText("No open positions.")).toBeInTheDocument();
  });

  it("puts the name's flags on its card once, not on every row", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/claude/context": { available: true, dossiers: [{ symbol: "AAPL", health: "weak", events: [] }] },
      "/portfolio/positions": positions([aapl]),
    });
    await screen.findByRole("heading", { name: "AAPL" });
    expect(await screen.findAllByText("Weak health")).toHaveLength(1);
  });

  it("says so in a sentence when positions cannot load", async () => {
    renderWithQuery(<PositionsView />, base);
    expect(await screen.findByText("Positions unavailable right now.")).toBeInTheDocument();
  });
});
