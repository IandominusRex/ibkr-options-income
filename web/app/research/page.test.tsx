import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { OPEN_SEARCH_EVENT } from "@/lib/search";
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

  it("opens the console's one palette when clicked, instead of mounting its own", () => {
    withClient(<Home />);
    const seen = vi.fn();
    window.addEventListener(OPEN_SEARCH_EVENT, seen);
    fireEvent.click(screen.getByRole("button", { name: /search a ticker/i }));
    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("puts Top opportunities above the watchlist", async () => {
    withClient(<Home />);
    const top = screen.getByRole("heading", { name: "Top opportunities" });
    const watch = await screen.findByRole("heading", { name: "Your watchlist" });
    expect(top.compareDocumentPosition(watch) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("group", { name: "Opportunity list" })).toBeDefined();
  });
});
