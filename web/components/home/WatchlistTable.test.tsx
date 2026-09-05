import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { WatchlistTable } from "./WatchlistTable";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>{ui}</QueryClientProvider>,
  );
}

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("WatchlistTable", () => {
  it("empty watchlist renders one line of text plus the action, no decorative icon", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", items: [] });
    withClient(<WatchlistTable />);
    expect(screen.getByText(/Your watchlist is empty/i)).toBeDefined();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("renders rows for each tracked symbol", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      items: [
        {
          symbol: "NVDA",
          name: "NVIDIA",
          price: { value: 120.0, source: "yfinance", as_of: "x", stale: false },
          change_pct: 1.5,
          iv_rank: 80.0,
          checks: { passed: 3, evaluable: 5, unknown: 1 },
          next_earnings: null,
        },
      ],
    });
    withClient(<WatchlistTable />);
    expect(await screen.findByText("NVDA")).toBeDefined();
  });
});