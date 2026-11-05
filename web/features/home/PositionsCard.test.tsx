import { fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import type { StrategyFilter } from "@/lib/strategy";
import { PositionsCard } from "./PositionsCard";

const positions = {
  as_of: new Date().toISOString(),
  source: "monitor",
  degraded: false,
  groups: [
    {
      as_of: "",
      underlying: "AMD",
      stock: null,
      options: [
        { as_of: "", symbol: "x", right: "P", strike: 150, expiry: "2099-10-24", dte: 11, contracts: 1, short: true, delta: null, delta_source: null, market_price: null, market_value: null, unrealized_pnl: -212, moneyness: "itm", assignment_risk: true },
      ],
    },
    {
      as_of: "",
      underlying: "KO",
      stock: null,
      options: [
        { as_of: "", symbol: "y", right: "C", strike: 72, expiry: "2099-11-14", dte: 32, contracts: 1, short: true, delta: null, delta_source: null, market_price: null, market_value: null, unrealized_pnl: 30, moneyness: "otm", assignment_risk: false },
      ],
    },
  ],
};

const spreadsOff = { as_of: "", available: false, underlying: "SPY", mode: "paper", positions: [] };
const spreadsOn = { as_of: "", available: true, underlying: "SPY", mode: "paper", positions: [] };

/** renderWithQuery's own `rerender` would drop the QueryClientProvider, so the page's
 *  strategy switcher is stood in for by a harness that holds the prop in state. */
function Harness() {
  const [s, setS] = useState<StrategyFilter>("cc");
  return (
    <>
      <button onClick={() => setS("csp")}>to csp</button>
      <PositionsCard strategy={s} />
    </>
  );
}

describe("PositionsCard", () => {
  it("lists rows and counts per strategy chip", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOn });
    expect(await screen.findByText("AMD $150 put")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "CSPs 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "CCs 1" })).toBeInTheDocument();
  });
  it("follows the page's strategy switcher, and its own chips narrow further", async () => {
    renderWithQuery(<Harness />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOn });
    expect(await screen.findByText("KO $72 call")).toBeInTheDocument();
    expect(screen.queryByText("AMD $150 put")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "All 2" }));
    expect(screen.getByText("AMD $150 put")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "to csp" }));
    expect(screen.queryByText("KO $72 call")).toBeNull();
    expect(screen.getByText("AMD $150 put")).toBeInTheDocument();
  });
  it("renders option rows when spreads are unavailable", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions });
    expect(await screen.findByText("AMD $150 put")).toBeInTheDocument();
  });
  it("says nothing is open for an empty filter, in words", async () => {
    renderWithQuery(<PositionsCard strategy="spread" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOn });
    expect(await screen.findByText("No credit spreads open.")).toBeInTheDocument();
  });
  it("names the filter in its empty copy", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOn });
    await screen.findByText("AMD $150 put");
    fireEvent.click(screen.getByRole("button", { name: /^Shares/ }));
    expect(screen.getByText("No shares held.")).toBeInTheDocument();
    expect(screen.queryByText("AMD $150 put")).toBeNull();
  });
  it("tells no snapshot apart from no positions", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, {
      "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": { ...positions, source: "none", groups: [] },
      "/spreads/positions": spreadsOn,
    });
    expect(await screen.findByText("No positions captured yet.")).toBeInTheDocument();
  });
  it("does not say no spreads are open when the spreads book cannot be read", async () => {
    renderWithQuery(<PositionsCard strategy="spread" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOff });
    expect(await screen.findByText("Credit spreads are unavailable right now.")).toBeInTheDocument();
    expect(screen.queryByText("No credit spreads open.")).toBeNull();
  });
  it("lists the options and notes what is missing under All when spreads cannot be read", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOff });
    expect(await screen.findByText("AMD $150 put")).toBeInTheDocument();
    expect(await screen.findByText("Credit spreads are unavailable right now, so they are not listed.")).toBeInTheDocument();
  });
  it("shows no count on the spreads chip until the spreads book has answered", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOff });
    await screen.findByText("AMD $150 put");
    expect(screen.getByRole("button", { name: "Credit spreads" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Credit spreads 0" })).toBeNull();
  });
  it("signs the open P&L in words and symbols", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOn });
    expect(await screen.findByText("−$212.00")).toBeInTheDocument();
    expect(screen.getByText("+$30.00")).toBeInTheDocument();
    expect(screen.getAllByText("open P&L")).toHaveLength(2);
  });
  it("flags a delayed snapshot in words rather than passing it off as live", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, {
      "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": { ...positions, source: "eod", degraded: true, as_of: "2020-01-01T00:00:00Z" },
      "/spreads/positions": spreadsOn,
    });
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.getByText(/stale/)).toBeInTheDocument();
  });
  it("says so in a sentence when positions cannot load", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, {});
    expect(await screen.findByText("Positions unavailable right now.")).toBeInTheDocument();
  });
  describe("search", () => {
    const rich = {
      ...positions,
      groups: [
        ...positions.groups,
        {
          as_of: "",
          underlying: "NVDA",
          stock: null,
          options: [
            { as_of: "", symbol: "z", right: "C", strike: 165, expiry: "2099-11-21", dte: 39, contracts: 1, short: true, delta: null, delta_source: null, market_price: null, market_value: null, unrealized_pnl: 61, moneyness: "otm", assignment_risk: false },
          ],
        },
      ],
    };
    const serve = { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": rich, "/spreads/positions": spreadsOn };
    const type = (text: string) =>
      fireEvent.change(screen.getByRole("textbox", { name: "Search positions" }), { target: { value: text } });

    it("filters the rows to a ticker as you type, in any case", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve);
      await screen.findByText("AMD $150 put");
      type("nv");
      expect(screen.getByText("NVDA $165 call")).toBeInTheDocument();
      expect(screen.queryByText("AMD $150 put")).toBeNull();
      expect(screen.queryByText("KO $72 call")).toBeNull();
    });
    it("takes several names separated by commas", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve);
      await screen.findByText("AMD $150 put");
      type("amd, ko");
      expect(screen.getByText("AMD $150 put")).toBeInTheDocument();
      expect(screen.getByText("KO $72 call")).toBeInTheDocument();
      expect(screen.queryByText("NVDA $165 call")).toBeNull();
    });
    it("makes each chip's count say what it would show with the search applied", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve);
      await screen.findByText("AMD $150 put");
      expect(screen.getByRole("button", { name: "All 3" })).toBeInTheDocument();
      type("amd");
      expect(screen.getByRole("button", { name: "All 1" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "CSPs 1" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "CCs 0" })).toBeInTheDocument();
    });
    it("composes with the chips", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve);
      await screen.findByText("AMD $150 put");
      fireEvent.click(screen.getByRole("button", { name: /^CCs/ }));
      type("amd");
      expect(screen.getByText('No positions match "amd".')).toBeInTheDocument();
    });
    it("says nothing matches, in words, and clears with one tap", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve);
      await screen.findByText("AMD $150 put");
      type("tsla");
      expect(screen.getByText('No positions match "tsla".')).toBeInTheDocument();
      expect(screen.queryByText("No positions captured yet.")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
      expect(screen.getByText("AMD $150 put")).toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: "Search positions" })).toHaveValue("");
      expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
    });
    it("is a labelled search landmark", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve);
      await screen.findByText("AMD $150 put");
      expect(screen.getByRole("search")).toBeInTheDocument();
    });
  });

  it("opens each contract's own page from its row", async () => {
    renderWithQuery(<PositionsCard strategy="all" />, { "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": positions, "/spreads/positions": spreadsOn });
    const link = (await screen.findByText("AMD $150 put")).closest("a");
    expect(link).toHaveAttribute("href", "/positions/AMD/2099-10-24_P150");
    expect(screen.getByText("KO $72 call").closest("a")).toHaveAttribute("href", "/positions/KO/2099-11-14_C72");
  });

  it("marks a short option the monitor raised a roll alert on, in words", async () => {
    const group = {
      as_of: "", underlying: "AAPL", stock: null,
      options: [{
        as_of: "", symbol: "AAPL  261121P00180000", right: "P", strike: 180, expiry: "2099-11-21", dte: 30,
        contracts: 1, short: true, delta: -0.2, delta_source: "ibkr", market_price: 0.6, market_value: -60,
        unrealized_pnl: 175, moneyness: "otm", assignment_risk: false,
      }],
    };
    renderWithQuery(<PositionsCard strategy="all" />, {
      "/portfolio/positions": { as_of: new Date().toISOString(), source: "monitor", degraded: false, groups: [group] },
      "/spreads/positions": { as_of: "", available: true, underlying: "SPY", mode: "paper", positions: [] },
      "/options/shorts": {
        as_of: "",
        shorts: [{
          position_symbol: "AAPL  261121P00180000",
          alerts: [{ id: 1, trigger: "delta_breach", trigger_label: "Delta breach", detail: "", claude_recommendation: null, created_at: "" }],
        }],
      },
    });
    const row = await screen.findByRole("link", { name: /AAPL \$180 put/ });
    expect(within(row).getByText("Roll alert")).toBeInTheDocument();
  });
  describe("the value book", () => {
    const vpos = (over: Record<string, unknown> = {}) => ({
      id: 1, symbol: "AAPL", list_name: "quality_growth", status: "open", shares: 10, avg_cost: 170, mark: 180,
      opened_at: "2026-10-01T00:00:00Z", closed_on: null, next_exit: { kind: "sell_half", level: 210 }, realised_usd: null,
      ...over,
    });
    const valueOn = (rows: unknown[] = [vpos()]) => ({ as_of: "", available: true, status: "open", positions: rows });
    const valueOff = { as_of: "", available: false, status: "open", positions: [] };
    // The wheel holds 100 AAPL shares itself: the same name, a different book.
    const wheel = {
      ...positions,
      groups: [
        ...positions.groups,
        {
          as_of: "", underlying: "AAPL", options: [],
          stock: { shares: 100, avg_cost: 150, adjusted_cost_basis: 148, unrealized_pnl: 3000, unrealized_pnl_adjusted: 3200 },
        },
      ],
    };
    const serve = (value: unknown, pos: unknown = wheel) => ({
      "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": pos, "/spreads/positions": spreadsOn,
      "/value/positions": value,
    });

    it("lists the book's shares with their average cost and next exit under Value", async () => {
      renderWithQuery(<PositionsCard strategy="value" />, serve(valueOn()));
      expect(await screen.findByText("AAPL · 10 shares")).toBeInTheDocument();
      expect(screen.getByText(/average cost \$170\.00/)).toBeInTheDocument();
      expect(screen.getByText(/next exit: sell half at \$210\.00/)).toBeInTheDocument();
      expect(screen.queryByText("AAPL · 100 shares")).toBeNull();
      expect(screen.queryByText("AMD $150 put")).toBeNull();
    });
    it("asks the value book for its open positions", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve(valueOn()));
      await screen.findByText("AAPL · 10 shares");
      expect(apiFetchMock.mock.calls.some((c) => c[0] === "/value/positions?status=open")).toBe(true);
    });
    it("adds them under All as a Value book group, apart from the wheel's share row on the same name", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve(valueOn()));
      const mine = await screen.findByText("AAPL · 100 shares");
      const book = await screen.findByText("AAPL · 10 shares");
      expect(mine).not.toBe(book);
      const group = screen.getByRole("heading", { name: "Value book" }).parentElement as HTMLElement;
      expect(within(group).getByText("AAPL · 10 shares")).toBeInTheDocument();
      expect(within(group).queryByText("AAPL · 100 shares")).toBeNull();
      // Two counts, never one: the chips keep the wheel's shares and the book's apart.
      expect(screen.getByRole("button", { name: "Shares 1" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Value 1" })).toBeInTheDocument();
    });
    it("keeps the wheel's own rows out of the group, and the book's out of the Shares chip", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve(valueOn()));
      await screen.findByText("AAPL · 10 shares");
      fireEvent.click(screen.getByRole("button", { name: /^Shares/ }));
      expect(screen.getByText("AAPL · 100 shares")).toBeInTheDocument();
      expect(screen.queryByText("AAPL · 10 shares")).toBeNull();
    });
    it("names the group as the value book in words, also when it is the only one shown", async () => {
      renderWithQuery(<PositionsCard strategy="value" />, serve(valueOn()));
      const row = (await screen.findByText("AAPL · 10 shares")).closest("li") as HTMLElement;
      const group = screen.getByRole("heading", { name: "Value book" }).parentElement as HTMLElement;
      expect(group).toContainElement(row);
    });
    it("reads a name with no average cost or exit level in words, never $0", async () => {
      renderWithQuery(<PositionsCard strategy="value" />, serve(valueOn([vpos({ avg_cost: null, mark: null, next_exit: null })])));
      expect(await screen.findByText(/average cost not recorded/)).toBeInTheDocument();
      expect(screen.getByText(/next exit not set/)).toBeInTheDocument();
      expect(screen.getByText("n/a")).toHaveClass("hatch");
    });
    it("says the book holds no shares, in words, when it is readable and empty", async () => {
      renderWithQuery(<PositionsCard strategy="value" />, serve(valueOn([])));
      expect(await screen.findByText("The value book holds no shares.")).toBeInTheDocument();
    });
    it("says the book could not be read, never that it is empty", async () => {
      renderWithQuery(<PositionsCard strategy="value" />, serve(valueOff));
      expect(await screen.findByText("The value book could not be read, so its shares are not listed.")).toBeInTheDocument();
      expect(screen.queryByText("The value book holds no shares.")).toBeNull();
    });
    it("lists the options and notes the unread book under All, with no count on the Value chip", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve(valueOff));
      expect(await screen.findByText("AMD $150 put")).toBeInTheDocument();
      expect(await screen.findByText("The value book could not be read, so its shares are not listed.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Value" })).toBeInTheDocument();
    });
    it("finds a value row by its ticker in the search", async () => {
      renderWithQuery(<PositionsCard strategy="all" />, serve(valueOn([vpos(), vpos({ id: 2, symbol: "MSFT" })])));
      await screen.findByText("MSFT · 10 shares");
      fireEvent.change(screen.getByRole("textbox", { name: "Search positions" }), { target: { value: "msft" } });
      expect(screen.getByText("MSFT · 10 shares")).toBeInTheDocument();
      expect(screen.queryByText("AAPL · 10 shares")).toBeNull();
    });
  });
});
