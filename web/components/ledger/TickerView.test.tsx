import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { TickerView } from "./TickerView";

vi.mock("next/navigation", () => ({ usePathname: () => "/ledger/ticker/AMZN" }));

const ISO = new Date().toISOString();
const DETAIL = {
  ticker: {
    symbol: "AMZN", currency: "USD", option_premium_gross: 578, option_net_pnl: 575.86, stock_realized: 0,
    dividends_net: 0, total_realized: 575.86, unrealized: null, n_trades: 2, n_open: 1, n_closed: 1,
    win_rate: 1, avg_premium: 177, best_trade: 175.86, worst_trade: 175.86, annualised_return_pct: 40,
    shares_held: 100, broker_avg_cost: 215, wheel_adjusted_basis: 209.2414, first_trade: "2025-10-03", last_trade: "2025-10-20",
  },
  trades: [], lots: [{ lot_key: "k", underlying: "AMZN", currency: "USD", acquired_date: "2025-10-10", source: "assigned", quantity: 100, remaining: 100, cost_per_share: 215 }],
  disposals: [], dividends: [],
  basis_walk: [
    { point_date: "2025-10-10", label: "Shares acquired", basis_per_share: 215 },
    { point_date: "2025-10-20", label: "Sell 235C Open", basis_per_share: 209.2414 },
  ],
};

describe("TickerView", () => {
  it("shows broker cost and wheel-adjusted basis side by side", async () => {
    renderWithQuery(<TickerView symbol="amzn" />, {
      "/ledger/tickers/AMZN": { as_of: ISO, detail: DETAIL },
      "/ledger/trades": { as_of: ISO, n: 0, trades: [], filters: {} },
    });
    expect(await screen.findByTestId("tile-broker-cost")).toHaveTextContent("$215.00");
    expect(screen.getByTestId("tile-wheel-basis")).toHaveTextContent("$209.24");
    expect(screen.getByText("assigned")).toBeInTheDocument();
    expect(screen.getAllByText(/Sell 235C Open/).length).toBeGreaterThan(0);
  });

  it("says so when the ticker has no history", async () => {
    // Set the 404 BEFORE rendering: renderWithQuery would install its own map, and the
    // query fires during render's act() flush.
    apiFetchMock.mockImplementation(async () => { throw new ApiError(404, "No ledger history"); });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><TickerView symbol="ZZZZ" /></QueryClientProvider>);
    expect(await screen.findByText(/No ledger history for ZZZZ/)).toBeInTheDocument();
  });
});
