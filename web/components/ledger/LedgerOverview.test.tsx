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

  it("labels the P&L curve as excluding interest and fees", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [aTicker()] },
    });
    expect(await screen.findByTestId("curve-caption")).toHaveTextContent(/interest and fees/);
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

  it("leads to the trades list and the statement import, and has no sub-navigation of its own", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    expect(await screen.findByRole("link", { name: "All trades" })).toHaveAttribute("href", "/ledger/trades");
    expect(screen.getByRole("link", { name: "Import a statement" })).toHaveAttribute("href", "/ledger/import");
    expect(screen.queryByRole("navigation", { name: "Ledger sections" })).toBeNull();
  });

  it("says where its figures come from, and that they can differ from the system's own", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    expect(
      await screen.findByText(/What IBKR reports, from the live feed, the Flex query and statement imports/),
    ).toBeInTheDocument();
    expect(screen.getByText(/It can differ from the system's own record under Pay/)).toBeInTheDocument();
  });

  it("lists upcoming expiries with a link to the ticker and the outcome in words", async () => {
    const upcoming = {
      order_key: "k1", underlying: "NVDA", side: "Sell", lots: 1, strike: 138, right: "P",
      expiry: "2099-11-20", outcome: "Open", outcome_overridden: false,
    };
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary({ upcoming: [upcoming as never] }) },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    const link = await screen.findByRole("link", { name: "NVDA" });
    expect(link).toHaveAttribute("href", "/ledger/ticker/NVDA");
    const row = link.closest("li") as HTMLElement;
    expect(row).toHaveTextContent("Sell 1 x 138P");
    expect(row).toHaveTextContent("Open");
  });

  it("says it could not load the ledger, and shows nothing else, when the summary fails", async () => {
    renderWithQuery(<LedgerOverview />, { "/ledger/tickers": { as_of: ISO, tickers: [] } });
    expect(await screen.findByText("Could not load the ledger.")).toBeInTheDocument();
    expect(screen.queryByTestId("ledger-tiles")).toBeNull();
  });

  it("keeps the page in one column that cannot outgrow the phone, so its tables scroll inside their cards", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [aTicker()] },
    });
    expect(await screen.findByTestId("ledger-overview")).toHaveClass("grid-cols-1");
  });

  it("says a bucket table is empty instead of showing only its headings", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": {
        as_of: ISO,
        summary: aSummary({ by_strategy: [{ label: "CSP", n_closed: 4, realized_usd: 900, win_rate: 0.75 }], by_book: [] }),
      },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    const book = await screen.findByTestId("buckets-book");
    expect(within(book).getByText("None yet.")).toBeInTheDocument();
    expect(within(book).queryByRole("table")).toBeNull();
    expect(within(await screen.findByTestId("buckets-strategy")).getByRole("table")).toBeInTheDocument();
  });
});
