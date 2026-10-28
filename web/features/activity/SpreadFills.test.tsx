import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SpreadFills } from "./SpreadFills";

const order = (over: Record<string, unknown> = {}) => ({
  spread_id: "s1", kind: "close", ib_order_id: 11, perm_id: 4001, filled_qty: 2, price: 0.05,
  commission: 2.6, reason: "profit_take", created_at: "2026-10-15T14:33:50Z", mode: "paper", side: "put",
  expiry: "2026-10-15", short_strike: 763, long_strike: 758, ...over,
});
const body = (orders: unknown[], over: Record<string, unknown> = {}) => ({
  as_of: "", available: true, underlying: "SPY", orders, ...over,
});
const serve = (b: unknown) => renderWithQuery(<SpreadFills days={30} />, { "/spreads/orders": b });

describe("SpreadFills", () => {
  it("lists the book's filled orders with the spread, what was done, the reason and the price", async () => {
    serve(body([order()]));
    expect(await screen.findByText("SPY 763/758 put spread")).toBeInTheDocument();
    expect(screen.getByText("Closed")).toBeInTheDocument();
    expect(screen.getByText("paper")).toBeInTheDocument();
    expect(screen.getByText("Reason: profit take")).toBeInTheDocument();
    expect(screen.getByText("$0.05")).toBeInTheDocument();
    expect(screen.getByText(/2 contracts/)).toBeInTheDocument();
  });

  it("says a price it does not have is n/a, and a spread it cannot identify", async () => {
    serve(body([order({ price: null, short_strike: null, long_strike: null, side: null, mode: null })]));
    expect(await screen.findByText("SPY credit spread, strikes n/a")).toBeInTheDocument();
    expect(screen.getByText("n/a")).toHaveClass("hatch");
  });

  it("says the book is unavailable, not empty, when the file cannot be read", async () => {
    serve(body([], { available: false }));
    expect(await screen.findByText("Credit spread fills are unavailable right now.")).toBeInTheDocument();
    expect(screen.queryByText(/No credit spread orders/)).toBeNull();
  });

  it("says unavailable when the request fails", async () => {
    renderWithQuery(<SpreadFills days={30} />, {});
    expect(await screen.findByText("Credit spread fills are unavailable right now.")).toBeInTheDocument();
  });

  it("says there are none in the window when the book is readable and empty", async () => {
    serve(body([]));
    expect(await screen.findByText("No credit spread orders in the last 30 days.")).toBeInTheDocument();
  });
});
