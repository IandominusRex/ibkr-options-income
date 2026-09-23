import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { OrdersTable } from "./OrdersTable";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("OrdersTable", () => {
  it("renders the empty state when there are no working orders", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", orders: [] });
    withClient(<OrdersTable />);
    expect(await screen.findByText(/No working orders/i)).toBeDefined();
  });

  it("renders a null avg_fill_price as n/a, never 0.00", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      orders: [
        {
          as_of: "x",
          id: 1,
          candidate_id: "c1",
          approval_id: null,
          underlying: "NVDA",
          strategy: "cash_secured_put",
          strike: 190.0,
          expiry: null,
          state: "submitted",
          limit_price: 3.25,
          filled_qty: 0,
          avg_fill_price: null,
          is_live: false,
          detail: null,
          created_at: "x",
          updated_at: "x",
        },
      ],
    });
    withClient(<OrdersTable />);
    expect(await screen.findByText("NVDA")).toBeDefined();
    const cells = screen.getAllByText("n/a");
    expect(cells.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("$0.00")).toBeNull();
  });

  it("renders order state with a label, never colour alone", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      orders: [
        {
          as_of: "x",
          id: 1,
          candidate_id: "c1",
          approval_id: null,
          underlying: "NVDA",
          strategy: "cash_secured_put",
          strike: 190.0,
          expiry: null,
          state: "submitted",
          limit_price: 3.25,
          filled_qty: 0,
          avg_fill_price: null,
          is_live: false,
          detail: null,
          created_at: "x",
          updated_at: "x",
        },
      ],
    });
    withClient(<OrdersTable />);
    expect(await screen.findByText("Submitted")).toBeDefined();
  });

  it("asserts no roll button exists", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", orders: [] });
    withClient(<OrdersTable />);
    await screen.findByText(/No working orders/i);
    expect(screen.queryAllByRole("button", { name: /roll/i })).toHaveLength(0);
  });

  it("shows a rejected order's humanised detail, and defaults to the Working filter", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockImplementation(async (path: string) => {
      if (path.includes("state=working")) return { as_of: "x", orders: [] };
      if (path.includes("state=rejected")) {
        return {
          as_of: "x",
          orders: [
            {
              as_of: "x",
              id: 2,
              candidate_id: "c2",
              approval_id: 1,
              underlying: "TSLA",
              strategy: "cash_secured_put",
              strike: 260.0,
              expiry: null,
              state: "rejected",
              limit_price: 4.1,
              filled_qty: 0,
              avg_fill_price: null,
              is_live: true,
              detail:
                "Live re-validation failed: live mid collapsed well below the approved premium (price moved against the trade)",
              created_at: "x",
              updated_at: "x",
            },
          ],
        };
      }
      return { as_of: "x", orders: [] };
    });
    withClient(<OrdersTable />);
    // Working is the default filter, and there are none — so nothing rejected
    // is visible until the Rejected filter is picked.
    expect(await screen.findByText(/No working orders/i)).toBeDefined();
    expect(screen.queryByText(/TSLA/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Rejected" }));
    expect(await screen.findByText("TSLA")).toBeDefined();
    expect(
      screen.getByText(/live mid collapsed well below the approved premium/),
    ).toBeDefined();
    // Never a raw Python list repr like "['live_premium_collapse']".
    expect(screen.queryByText(/live_premium_collapse/)).toBeNull();
  });
});