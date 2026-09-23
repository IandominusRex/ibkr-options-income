import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("can be curated: typing a symbol searches the research directory", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockImplementation(async (path: string) => {
      if (path.startsWith("/research/search")) {
        return {
          as_of: "x",
          query: "AAP",
          results: [
            { symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false },
          ],
        };
      }
      return { as_of: "x", items: [] };
    });
    withClient(<WatchlistTable />);
    fireEvent.change(screen.getByPlaceholderText(/add a symbol/i), {
      target: { value: "AAP" },
    });
    expect(await screen.findByText("Apple Inc.")).toBeDefined();
  });

  it("picking a hit adds it to the watchlist with no confirmation dialog", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.startsWith("/research/search")) {
        return {
          as_of: "x",
          query: "AAP",
          results: [
            { symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false },
          ],
        };
      }
      if (path === "/watchlist/AAPL" && init?.method === "POST") {
        return { symbol: "AAPL", added: true };
      }
      return { as_of: "x", items: [] };
    });
    withClient(<WatchlistTable />);
    fireEvent.change(screen.getByPlaceholderText(/add a symbol/i), {
      target: { value: "AAP" },
    });
    fireEvent.click(await screen.findByText("Apple Inc."));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/watchlist/AAPL",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("disables the add input while an add is in flight, so a double-pick cannot fire twice", async () => {
    const { apiFetch } = await import("@/lib/api");
    let resolvePost: (v: unknown) => void = () => {};
    (apiFetch as any).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.startsWith("/research/search")) {
        return {
          as_of: "x",
          query: "AAP",
          results: [
            { symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false },
          ],
        };
      }
      if (path === "/watchlist/AAPL" && init?.method === "POST") {
        return new Promise((r) => (resolvePost = r));
      }
      return { as_of: "x", items: [] };
    });
    withClient(<WatchlistTable />);
    fireEvent.change(screen.getByPlaceholderText(/add a symbol/i), {
      target: { value: "AAP" },
    });
    fireEvent.click(await screen.findByText("Apple Inc."));
    await waitFor(() =>
      expect((screen.getByPlaceholderText(/add a symbol/i) as HTMLInputElement).disabled).toBe(
        true,
      ),
    );
    resolvePost({ symbol: "AAPL", added: true });
  });

  it("disables a row's remove button while that row's remove is in flight", async () => {
    const { apiFetch } = await import("@/lib/api");
    let resolveDelete: (v: unknown) => void = () => {};
    (apiFetch as any).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/watchlist/NVDA" && init?.method === "DELETE") {
        return new Promise((r) => (resolveDelete = r));
      }
      return {
        as_of: "x",
        items: [
          {
            symbol: "NVDA",
            name: "NVIDIA",
            price: null,
            change_pct: null,
            iv_rank: null,
            checks: { passed: 0, evaluable: 0, unknown: 0 },
            next_earnings: null,
          },
        ],
      };
    });
    withClient(<WatchlistTable />);
    const remove = await screen.findByText("remove");
    fireEvent.click(remove);
    await waitFor(() => expect((remove as HTMLButtonElement).disabled).toBe(true));
    resolveDelete(undefined);
  });
});