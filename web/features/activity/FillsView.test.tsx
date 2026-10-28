import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { FillsView } from "./FillsView";

const world = (over: Record<string, unknown> = {}) => ({
  "/options/orders": { as_of: "", orders: [] },
  "/options/fills": { as_of: "", fills: [] },
  "/spreads/orders": { as_of: "", available: true, underlying: "SPY", orders: [] },
  "/ledger/executions": {
    as_of: "", days: 30, limit: 200, truncated: false,
    executions: [{
      id: 1, source: "live", exec_id: "e1", trade_time: "2026-10-22T18:31:07Z", trade_date: "2026-10-22",
      underlying: "NVDA", sec_type: "OPT", right: "P", strike: 165, expiry: "2026-11-20", multiplier: 100,
      currency: "USD", quantity: -1, price: 2.35, proceeds: 235, commission: -1.3, codes: "O", book: "system",
      ib_order_id: 11, perm_id: 900,
    }],
  },
  ...over,
});
const calls = () => apiFetchMock.mock.calls.map((c) => String(c[0]));

describe("FillsView", () => {
  it("opens on the system's orders and says whose record it is", async () => {
    renderWithQuery(<FillsView />, world());
    expect(await screen.findByText(/The system's record: the wheel orders it sent to IBKR/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Orders" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText(/No working orders/i)).toBeInTheDocument();
  });

  it("shows the system's fills and the credit-spread fills under their own headings", async () => {
    renderWithQuery(<FillsView />, world());
    fireEvent.click(await screen.findByRole("button", { name: "Fills" }));
    expect(await screen.findByRole("heading", { name: "Wheel" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Credit spreads" })).toBeInTheDocument();
    expect(await screen.findByText("No fills in the last 30 days.")).toBeInTheDocument();
    expect(await screen.findByText("No credit spread orders in the last 30 days.")).toBeInTheDocument();
  });

  it("keeps IBKR's executions apart, with their own source line, and does not reconcile them", async () => {
    renderWithQuery(<FillsView />, world());
    fireEvent.click(await screen.findByRole("button", { name: "At IBKR" }));
    expect(await screen.findByText("Sold 1 NVDA $165 put · Nov 20")).toBeInTheDocument();
    expect(screen.getByText(/IBKR's record: every execution the ledger holds/)).toBeInTheDocument();
    expect(screen.getByText(/if they disagree, the disagreement is the finding/)).toBeInTheDocument();
    // The system's own fills list is empty in this world, and this view does not pretend otherwise.
    expect(screen.queryByText("No fills in the last 30 days.")).toBeNull();
  });

  it("passes the chosen window to every list", async () => {
    renderWithQuery(<FillsView />, world());
    fireEvent.click(await screen.findByRole("button", { name: "90 days" }));
    fireEvent.click(await screen.findByRole("button", { name: "Fills" }));
    await screen.findByText("No fills in the last 90 days.");
    fireEvent.click(screen.getByRole("button", { name: "At IBKR" }));
    await screen.findByText("Sold 1 NVDA $165 put · Nov 20");
    const seen = calls();
    expect(seen).toContain("/options/fills?days=90&limit=500");
    expect(seen).toContain("/spreads/orders?days=90&limit=200");
    expect(seen).toContain("/ledger/executions?days=90&limit=200");
  });

  it("defaults the window to 30 days", async () => {
    renderWithQuery(<FillsView />, world());
    expect(await screen.findByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
  });
});
