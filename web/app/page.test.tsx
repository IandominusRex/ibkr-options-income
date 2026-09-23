import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import Home from "./page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(async (path: string) => {
    if (path.startsWith("/research/search")) {
      return { as_of: "x", query: "", results: [] };
    }
    if (path === "/watchlist") return { as_of: "x", items: [] };
    if (path === "/research/sectors") return { as_of: "x", sectors: [] };
    return {};
  }),
}));

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("Home — visible search bar", () => {
  it("renders a search bar trigger to the right of the Research heading", () => {
    withClient(<Home />);
    expect(screen.getByRole("button", { name: /search a ticker/i })).toBeDefined();
  });

  it("opens the same command palette as ⌘K when clicked", () => {
    withClient(<Home />);
    expect(screen.queryByPlaceholderText(/search a ticker or company/i)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /search a ticker/i }));
    expect(screen.getByPlaceholderText(/search a ticker or company/i)).toBeDefined();
  });
});
