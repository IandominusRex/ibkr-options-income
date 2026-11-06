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
    expect(await screen.findByText(/Your watchlist is empty/i)).toBeDefined();
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
    const remove = await screen.findByRole("button", { name: "Remove NVDA" });
    fireEvent.click(remove);
    await waitFor(() => expect((remove as HTMLButtonElement).disabled).toBe(true));
    resolveDelete(undefined);
  });

  it("is titled Your watchlist and points to the scan's own watchlist on Universe", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", items: [] });
    withClient(<WatchlistTable />);
    expect(screen.getByRole("heading", { level: 2, name: "Your watchlist" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Universe" }).getAttribute("href")).toBe("/research/universe");
  });

  it("holds its place while loading and says a failed read in words, never an empty list", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockImplementation(() => new Promise(() => {}));
    const { unmount } = withClient(<WatchlistTable />);
    expect(screen.getByRole("status", { name: "Loading your watchlist" })).toBeDefined();
    expect(screen.queryByText(/Your watchlist is empty/i)).toBeNull();
    unmount();
    (apiFetch as any).mockRejectedValue(new Error("down"));
    withClient(<WatchlistTable />);
    expect(await screen.findByText("Your watchlist could not be loaded right now.")).toBeDefined();
  });

  it("writes a row as words: the price, the day's move signed but not coloured, IV rank, checks and earnings", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      items: [
        {
          symbol: "NVDA", name: "NVIDIA",
          price: { value: 120.0, source: "yfinance", as_of: "x", stale: true },
          change_pct: -1.25, iv_rank: 80.0, checks: { passed: 3, evaluable: 5, unknown: 1 },
          next_earnings: "2026-11-19",
        },
        {
          symbol: "KO", name: "Coca-Cola", price: null, change_pct: null, iv_rank: null,
          checks: { passed: 0, evaluable: 0, unknown: 4 }, next_earnings: null,
        },
      ],
    });
    withClient(<WatchlistTable />);
    expect(await screen.findByText("$120.00")).toBeDefined();
    const move = screen.getByText("-1.25% today");
    expect(move.className).not.toMatch(/text-(gain|loss)/);
    expect(screen.getByText("Delayed")).toBeDefined();
    expect(screen.getByText("IV rank 80.0")).toBeDefined();
    expect(screen.getByText("3 of 5 checks pass")).toBeDefined();
    expect(screen.getByText("Earnings Nov 19, 2026")).toBeDefined();
    expect(screen.getByRole("link", { name: /NVDA/ }).getAttribute("href")).toBe("/stock/NVDA");
    // KO: every unknown is a hatched n/a, never $0 or 0 of 0.
    expect(screen.getAllByText("n/a").length).toBe(4);
    expect(screen.queryByText("0 of 0 checks pass")).toBeNull();
    expect(document.querySelector(".text-gain, .text-loss")).toBeNull();
  });

  it("says a failed add in words", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.startsWith("/research/search")) {
        return { as_of: "x", query: "AAP", results: [{ symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false }] };
      }
      if (init?.method === "POST") throw new Error("down");
      return { as_of: "x", items: [] };
    });
    withClient(<WatchlistTable />);
    fireEvent.change(screen.getByPlaceholderText(/add a symbol/i), { target: { value: "AAP" } });
    fireEvent.click(await screen.findByText("Apple Inc."));
    expect(await screen.findByText("That name could not be added. Nothing changed.")).toBeDefined();
  });
  it("hides the separator dots from a screen reader, so a row's name reads as words", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      items: [
        {
          symbol: "NVDA", name: "NVIDIA",
          price: { value: 120.0, source: "yfinance", as_of: "x", stale: false },
          change_pct: 1.5, iv_rank: 80.0, checks: { passed: 3, evaluable: 5, unknown: 1 },
          next_earnings: "2026-11-19",
        },
      ],
    });
    withClient(<WatchlistTable />);
    const link = await screen.findByRole("link", { name: /NVDA/ });
    expect(link.textContent).toContain("·");
    expect(link).not.toHaveAccessibleName(/·/);
  });

  it("says a failed ticker search in words, not 'no ticker matches'", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockImplementation(async (path: string) => {
      if (path.startsWith("/research/search")) throw new Error("down");
      return { as_of: "x", items: [] };
    });
    withClient(<WatchlistTable />);
    fireEvent.change(screen.getByPlaceholderText(/add a symbol/i), { target: { value: "AAP" } });
    expect(await screen.findByText("Tickers could not be searched right now.")).toBeDefined();
    expect(screen.queryByText("No ticker matches yet.")).toBeNull();
  });
});
