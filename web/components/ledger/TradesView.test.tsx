import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { TradesView } from "./TradesView";
import type { LedgerTrade } from "./types";

vi.mock("next/navigation", () => ({ usePathname: () => "/ledger/trades" }));

const ISO = new Date().toISOString();

function aTrade(over: Partial<LedgerTrade> = {}): LedgerTrade {
  return {
    order_key: "0123456789abcdef", underlying: "NVDA", currency: "USD", side: "Sell", right: "P",
    strike: 138, expiry: "2025-06-27", multiplier: 100, lots: 1, order_date: "2025-06-17",
    open_time: ISO, close_date: "2025-06-27", dte: 10, days_held: 10, premium: 131,
    open_commission: -1.04, closes: [], outcome: "Bought back", computed_outcome: "Bought back",
    outcome_overridden: false, mixed_close: false, capital: 13800, pct_profit: 34.6467,
    net_pnl: 127, return_pct: 0.92, annualised_net_pct: 33.6, stock_gain: null, book: "manual",
    rolled_from: null, rolled_to: null, ibkr_realized_pnl: 127.69, exec_row_ids: [1, 2],
    notes: "", tags: [], exclude_from_stats: false, ...over,
  };
}

describe("TradesView", () => {
  it("renders the sheet columns and the sheet percentage", async () => {
    renderWithQuery(<TradesView />, { "/ledger/trades": { as_of: ISO, n: 1, trades: [aTrade()], filters: {} } });
    expect(await screen.findByText("34.65%")).toBeInTheDocument();
    for (const h of ["Sell/Buy", "Put/Call", "Order Date", "Expiry", "Ticker", "Lots", "Strike", "Premium", "Outcome", "DTE", "% Profit"]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
  });

  it("puts the filters into the request and the CSV link", async () => {
    renderWithQuery(<TradesView />, { "/ledger/trades": { as_of: ISO, n: 0, trades: [], filters: {} } });
    fireEvent.change(await screen.findByLabelText("Ticker"), { target: { value: "amzn" } });
    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "Expired" } });
    await waitFor(() => {
      const paths = apiFetchMock.mock.calls.map((c) => String(c[0]));
      expect(paths.some((p) => p.includes("symbol=AMZN") && p.includes("outcome=Expired"))).toBe(true);
    });
    expect(screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")).toContain("symbol=AMZN");
  });

  it("saves notes through a ledger_annotate command", async () => {
    renderWithQuery(<TradesView />, {
      "/ledger/trades/0123456789abcdef": { as_of: ISO, trade: aTrade(), executions: [] },
      "/ledger/trades": { as_of: ISO, n: 1, trades: [aTrade()], filters: {} },
      "/commands/77": { id: 77, kind: "ledger_annotate", status: "applied", result: {}, needs_confirmation: false, confirm_token: null, created_at: ISO, applied_at: ISO, as_of: ISO },
      "/commands": { id: 77, kind: "ledger_annotate", status: "pending", result: null, needs_confirmation: false, confirm_token: null, created_at: ISO, applied_at: null, as_of: ISO, created: true },
    });
    fireEvent.click(await screen.findByText("NVDA"));
    fireEvent.change(await screen.findByLabelText("Notes"), { target: { value: "near-zero buyback" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === "/commands");
      expect(post).toBeTruthy();
      const body = JSON.parse((post![1] as RequestInit).body as string);
      expect(body).toMatchObject({ kind: "ledger_annotate", payload: { order_key: "0123456789abcdef", notes: "near-zero buyback" } });
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });
});
