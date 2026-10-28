import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { FillsTable } from "./FillsTable";

const fill = (over: Record<string, unknown> = {}) => ({
  as_of: "", id: 1, order_id: 2, candidate_id: "c2", action: "SELL", filled_qty: 1, avg_price: 3.1,
  commission: 1.3, is_live: false, filled_at: "2026-10-22T18:31:00Z", underlying: "AAPL",
  strategy: "cash_secured_put", right: "P", strike: 185, expiry: "2026-11-20", ...over,
});
const serve = (fills: unknown[], days?: number) =>
  renderWithQuery(<FillsTable days={days} />, { "/options/fills": { as_of: "", fills } });

describe("FillsTable", () => {
  it("names the contract, the action, the price and when, in New York time", async () => {
    serve([fill()]);
    expect(await screen.findByText("AAPL $185 put")).toBeInTheDocument();
    expect(screen.getByText("SELL 1")).toBeInTheDocument();
    expect(screen.getByText("$3.10")).toBeInTheDocument();
    expect(screen.getByText(/Thu, Oct 22 · 2:31 PM ET/)).toBeInTheDocument();
    expect(screen.getByText(/paper/)).toBeInTheDocument();
  });

  it("says the commission is unknown rather than $0", async () => {
    serve([fill({ commission: null })]);
    await screen.findByText("AAPL $185 put");
    expect(screen.getByText("commission").parentElement).toHaveTextContent("commission n/a");
    expect(screen.queryByText("$0.00")).toBeNull();
  });

  it("says the contract is not on record, with the candidate id, when the order and candidate are gone", async () => {
    serve([fill({ underlying: null, strategy: null, right: null, strike: null, expiry: null, candidate_id: "ghost" })]);
    expect(await screen.findByText("Contract not on record")).toBeInTheDocument();
    expect(screen.getByText("ghost")).toBeInTheDocument();
  });

  it("asks for the window, and keeps the old seven days by default", async () => {
    serve([fill()]);
    await screen.findByText("AAPL $185 put");
    expect(apiFetchMock.mock.calls.map((c) => c[0])).toContain("/options/fills?days=7&limit=500");
  });

  it("says there are none in the window, in words", async () => {
    serve([], 30);
    expect(await screen.findByText("No fills in the last 30 days.")).toBeInTheDocument();
  });

  it("says the list was cut at 500", async () => {
    serve(Array.from({ length: 500 }, (_, i) => fill({ id: i + 1 })));
    expect(await screen.findByText("Showing the latest 500 fills. Choose a shorter window to see every fill in it.")).toBeInTheDocument();
  });

  it("says it could not load", async () => {
    renderWithQuery(<FillsTable />, {});
    expect(await screen.findByText("Could not load fills")).toBeInTheDocument();
  });
});
