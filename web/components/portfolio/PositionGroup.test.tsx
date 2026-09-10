import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { PositionGroup } from "./PositionGroup";
import { PositionsPanel } from "./PositionsPanel";
import type { OptionLeg, PositionGroupData, StockLeg } from "./types";

// Task 3.3 — all four components' tests live here (PositionsPanel, PositionGroup,
// OptionLegRow, StockLegRow), per the task brief's Files line naming only
// PositionGroup.test.tsx despite four components being built.

const ISO = new Date().toISOString();

function aStock(overrides: Partial<StockLeg> = {}): StockLeg {
  return {
    as_of: ISO,
    shares: 100,
    avg_cost: 190,
    adjusted_cost_basis: null,
    market_price: 205,
    market_value: 20_500,
    unrealized_pnl: 1_500,
    unrealized_pnl_adjusted: null,
    ...overrides,
  };
}

function anOption(overrides: Partial<OptionLeg> = {}): OptionLeg {
  return {
    as_of: ISO,
    symbol: "AAPL  260116C00220000",
    right: "C",
    strike: 220,
    expiry: "2026-01-16",
    dte: 40,
    contracts: 1,
    short: true,
    delta: -0.28,
    delta_source: "ibkr",
    market_price: 3.2,
    market_value: 320,
    unrealized_pnl: 45,
    moneyness: "otm",
    assignment_risk: false,
    ...overrides,
  };
}

function aGroup(overrides: Partial<PositionGroupData> = {}): PositionGroupData {
  return {
    as_of: ISO,
    underlying: "AAPL",
    stock: aStock(),
    options: [anOption()],
    ...overrides,
  };
}

describe("PositionGroup", () => {
  it("renders the underlying once, the stock leg above its option legs", () => {
    render(<PositionGroup group={aGroup()} />);

    expect(screen.getAllByRole("heading", { name: "AAPL" })).toHaveLength(1);

    const stockEl = screen.getByTestId("stock-leg");
    const optionEl = screen.getAllByTestId("option-leg")[0];
    // Node.DOCUMENT_POSITION_FOLLOWING === 4: optionEl comes after stockEl.
    expect(
      // eslint-disable-next-line no-bitwise
      stockEl.compareDocumentPosition(optionEl) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("renders both cost bases when adjusted_cost_basis is present, the premium-adjusted one identified in words", () => {
    render(
      <PositionGroup
        group={aGroup({
          stock: aStock({ avg_cost: 190, adjusted_cost_basis: 175, unrealized_pnl_adjusted: 3_000 }),
          options: [],
        })}
      />,
    );

    expect(screen.getAllByText(/premium-adjusted/i).length).toBeGreaterThan(0);
    expect(screen.getByText("$190.00")).toBeInTheDocument();
    expect(screen.getByText("$175.00")).toBeInTheDocument();
  });

  it("renders no adjusted-basis row when the shares did not come from an assignment", () => {
    render(
      <PositionGroup
        group={aGroup({
          stock: aStock({ adjusted_cost_basis: null, unrealized_pnl_adjusted: null }),
          options: [],
        })}
      />,
    );

    expect(screen.queryByText(/adjusted/i)).toBeNull();
  });

  it("labels a short leg as short in text, not only by a negative contract count", () => {
    render(
      <PositionGroup
        group={aGroup({ stock: null, options: [anOption({ short: true, contracts: 1 })] })}
      />,
    );

    expect(screen.getByTestId("option-direction")).toHaveTextContent(/short/i);
  });

  it("labels a long leg as long, not short, in text", () => {
    render(
      <PositionGroup
        group={aGroup({ stock: null, options: [anOption({ short: false, contracts: 2 })] })}
      />,
    );

    expect(screen.getByTestId("option-direction")).toHaveTextContent(/long/i);
    expect(screen.getByTestId("option-direction")).not.toHaveTextContent(/short/i);
  });

  it("renders assignment_risk as a text label, not a coloured dot", () => {
    render(
      <PositionGroup
        group={aGroup({ stock: null, options: [anOption({ assignment_risk: true })] })}
      />,
    );

    expect(screen.getByText(/assignment risk/i)).toBeInTheDocument();
  });

  it("renders dte: null as n/a, never 0", () => {
    render(
      <PositionGroup group={aGroup({ stock: null, options: [anOption({ dte: null })] })} />,
    );

    expect(screen.getByTestId("option-dte")).toHaveTextContent(/n\/a/i);
    expect(screen.getByTestId("option-dte")).not.toHaveTextContent(/^0$/);
  });

  it("renders moneyness: null as n/a, never otm", () => {
    render(
      <PositionGroup
        group={aGroup({ stock: null, options: [anOption({ moneyness: null })] })}
      />,
    );

    expect(screen.getByTestId("option-moneyness")).toHaveTextContent(/n\/a/i);
    expect(screen.getByTestId("option-moneyness")).not.toHaveTextContent(/otm/i);
  });

  it("renders delta with its delta_source beside it, matching ShortsTable", () => {
    render(
      <PositionGroup
        group={aGroup({
          stock: null,
          options: [anOption({ delta: -0.32, delta_source: "ibkr" })],
        })}
      />,
    );

    const el = screen.getByTestId("option-delta");
    expect(el).toHaveTextContent("-0.32");
    expect(el).toHaveTextContent("ibkr");
  });
});

describe("PositionsPanel", () => {
  it("renders the empty state when no snapshot has been captured (source: none)", async () => {
    renderWithQuery(<PositionsPanel />, {
      "/portfolio/positions": { as_of: ISO, source: "none", degraded: true, groups: [] },
    });

    expect(await screen.findByRole("status")).toHaveTextContent(/no portfolio snapshot/i);
  });

  it("renders 'no open positions' when the account is captured but holds nothing (source: monitor)", async () => {
    renderWithQuery(<PositionsPanel />, {
      "/portfolio/positions": { as_of: ISO, source: "monitor", degraded: false, groups: [] },
    });

    expect(await screen.findByRole("status")).toHaveTextContent(/no open positions/i);
  });

  it("distinguishes an empty account from an uncaptured one", async () => {
    const { unmount } = renderWithQuery(<PositionsPanel />, {
      "/portfolio/positions": { as_of: ISO, source: "none", degraded: true, groups: [] },
    });
    const uncaptured = (await screen.findByRole("status")).textContent;
    unmount();

    renderWithQuery(<PositionsPanel />, {
      "/portfolio/positions": { as_of: ISO, source: "monitor", degraded: false, groups: [] },
    });
    const empty = (await screen.findByRole("status")).textContent;

    expect(empty).not.toEqual(uncaptured);
  });

  it("renders one PositionGroup per group in the response", async () => {
    renderWithQuery(<PositionsPanel />, {
      "/portfolio/positions": {
        as_of: ISO,
        source: "monitor",
        degraded: false,
        groups: [aGroup({ underlying: "AAPL" }), aGroup({ underlying: "MSFT", options: [] })],
      },
    });

    expect(await screen.findByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "MSFT" })).toBeInTheDocument();
  });
});
