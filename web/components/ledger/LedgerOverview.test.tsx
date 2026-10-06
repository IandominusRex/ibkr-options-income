import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { LedgerOverview } from "./LedgerOverview";
import type { LedgerSummary, LedgerTicker } from "./types";

vi.mock("next/navigation", () => ({ usePathname: () => "/ledger" }));

const ISO = new Date().toISOString();

function aSummary(over: Partial<LedgerSummary> = {}): LedgerSummary {
  return {
    total_realized_usd: 2575.84, interest_and_fees_usd: 0, contributed_usd: null,
    capital_utilised_usd: 17000, available_usd: null, unrealized_usd: null, win_rate: 0.75,
    n_trades: 6, n_open: 1, premium_this_month_usd: 401, months: [], curve: [],
    by_strategy: [], by_book: [], upcoming: [], fx_incomplete: false, orphan_closes: 0,
    unreviewed_corporate_actions: 0, marks_as_of: null, ...over,
  };
}

function aTicker(over: Partial<LedgerTicker> = {}): LedgerTicker {
  return {
    symbol: "AMZN", currency: "USD", option_premium_gross: 578, option_net_pnl: 575.86,
    stock_realized: 1999.98, dividends_net: 0, total_realized: 2575.84, unrealized: null,
    n_trades: 3, n_open: 0, n_closed: 3, win_rate: 1, avg_premium: 192.67, best_trade: 400,
    worst_trade: 175.86, annualised_return_pct: 42.1, shares_held: 0, broker_avg_cost: null,
    wheel_adjusted_basis: null, first_trade: "2025-06-25", last_trade: "2025-10-31", ...over,
  };
}

describe("LedgerOverview", () => {
  it("renders the headline tiles and says n/a for unknowns, never $0", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [aTicker()] },
    });
    const tiles = await screen.findByTestId("ledger-tiles");
    expect(within(tiles).getByText("$2,575.84")).toBeInTheDocument();
    expect(within(tiles).getByTestId("tile-contributed")).toHaveTextContent("n/a");
    expect(within(tiles).getByTestId("tile-available")).toHaveTextContent("n/a");
    expect(within(tiles).getByTestId("tile-win-rate")).toHaveTextContent("75%");
  });

  it("links each ticker to its drill-down page", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [aTicker()] },
    });
    const link = await screen.findByRole("link", { name: "AMZN" });
    expect(link).toHaveAttribute("href", "/ledger/ticker/AMZN");
  });

  it("breaks results down by strategy and by book", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary({
        by_strategy: [{ label: "CSP", n_closed: 4, realized_usd: 900, win_rate: 0.75 }],
        by_book: [{ label: "manual", n_closed: 4, realized_usd: 900, win_rate: 0.75 }],
      }) },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    expect(await screen.findByTestId("buckets-strategy")).toHaveTextContent("CSP");
    expect(screen.getByTestId("buckets-book")).toHaveTextContent("manual");
  });

  it("warns about orphan closes and missing FX", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary({ orphan_closes: 2, fx_incomplete: true }) },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    expect(await screen.findByText(/2 closing trades have no opening/)).toBeInTheDocument();
    expect(screen.getByText(/no FX rate yet/)).toBeInTheDocument();
  });
});
