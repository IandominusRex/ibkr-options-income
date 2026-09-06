import { render, screen } from "@testing-library/react";
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
});