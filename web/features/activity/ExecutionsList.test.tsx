import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ExecutionsList } from "./ExecutionsList";

const exec = (over: Record<string, unknown> = {}) => ({
  id: 1, source: "live", exec_id: "0000e1", trade_time: "2026-10-22T18:31:07Z", trade_date: "2026-10-22",
  underlying: "NVDA", sec_type: "OPT", right: "P", strike: 165, expiry: "2026-11-20", multiplier: 100,
  currency: "USD", quantity: -1, price: 2.35, proceeds: 235, commission: -1.3, codes: "O", book: "system",
  ib_order_id: 11, perm_id: 900, ...over,
});
const body = (executions: unknown[], over: Record<string, unknown> = {}) => ({
  as_of: "", days: 30, limit: 200, truncated: false, executions, ...over,
});
const serve = (b: unknown, days = 30) => renderWithQuery(<ExecutionsList days={days} />, { "/ledger/executions": b });

describe("ExecutionsList", () => {
  it("lists IBKR's executions with the contract, the book, the source, the price and the commission", async () => {
    serve(body([exec(), exec({ id: 2, quantity: 100, sec_type: "STK", right: null, strike: null, expiry: null, underlying: "AMZN", price: 205.5, book: "manual", source: "flex", commission: 0, exec_id: "x2" })]));
    // "System" and "Manual" are also book chips above the list, so each word is read inside its row.
    const [first, second] = await screen.findAllByRole("listitem");
    expect(within(first).getByText("Sold 1 NVDA $165 put · Nov 20")).toBeInTheDocument();
    expect(within(first).getByText("System")).toBeInTheDocument();
    expect(within(first).getByText(/Thu, Oct 22 · 2:31 PM ET · live feed/)).toBeInTheDocument();
    expect(within(first).getByText("$2.35")).toBeInTheDocument();
    expect(within(first).getByText(/commission \$1\.30/)).toBeInTheDocument();
    expect(within(second).getByText("Bought 100 AMZN shares")).toBeInTheDocument();
    expect(within(second).getByText("Manual")).toBeInTheDocument();
    expect(within(second).getByText(/Flex query/)).toBeInTheDocument();
  });

  it("says no commission was recorded rather than $0", async () => {
    serve(body([exec({ commission: 0 })]));
    expect(await screen.findByText(/commission none recorded/)).toBeInTheDocument();
    expect(screen.queryByText(/commission \$0/)).toBeNull();
  });

  it("asks the API for the window and the chosen book", async () => {
    serve(body([exec()]), 90);
    await screen.findAllByRole("listitem");
    fireEvent.click(screen.getByRole("button", { name: "Spreads" }));
    const calls = () => apiFetchMock.mock.calls.map((c) => String(c[0]));
    await waitFor(() => expect(calls()).toContain("/ledger/executions?days=90&limit=200&book=spreads"));
    expect(calls()).toContain("/ledger/executions?days=90&limit=200");
  });

  it("says the list was cut short", async () => {
    serve(body([exec()], { truncated: true }));
    expect(await screen.findByText("Showing the latest 200. Choose a shorter window to see every execution in it.")).toBeInTheDocument();
  });

  it("says where executions come from when there are none", async () => {
    serve(body([]));
    expect(
      await screen.findByText(
        "No executions at IBKR in the last 30 days. They arrive through the live feed, the Flex query or a statement import.",
      ),
    ).toBeInTheDocument();
  });

  it("says it could not load", async () => {
    renderWithQuery(<ExecutionsList days={30} />, {});
    expect(await screen.findByText("Could not load IBKR's executions.")).toBeInTheDocument();
  });
});
