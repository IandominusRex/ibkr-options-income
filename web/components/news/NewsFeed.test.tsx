import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { NewsFeed } from "./NewsFeed";

const ISO = new Date().toISOString();
const post = (id: number, kind: string, title: string) => ({
  id, kind, subject: null, posted_at: ISO, stage: "explained", critical: false, silent: false, has_chart: false,
  payload: { kind, title, emoji: "📰", when: ISO, grid: [], links: [], updates: [], sections: [] },
});

describe("NewsFeed", () => {
  it("lists posts and switches group with the chips", async () => {
    renderWithQuery(<NewsFeed />, {
      "/news/feed?limit=30": { as_of: ISO, available: true, posts: [post(2, "earnings", "AAPL earnings"), post(1, "macro_print", "CPI")] },
      "/news/feed?group=earnings&limit=30": { as_of: ISO, available: true, posts: [post(2, "earnings", "AAPL earnings")] },
      "/news/calendar?days=7": { as_of: ISO, available: true, econ: [], earnings: [] },
    });
    expect(await screen.findByText("CPI")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Earnings" }));
    expect(await screen.findByText("AAPL earnings")).toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => String(c[0]).includes("group=earnings"))).toBe(true);
  });

  it("filters by symbol once typing pauses, not on every keystroke", async () => {
    renderWithQuery(<NewsFeed />, {
      "/news/feed?limit=30": { as_of: ISO, available: true, posts: [post(1, "macro_print", "CPI")] },
      "/news/feed?symbol=NVDA&limit=30": { as_of: ISO, available: true, posts: [post(3, "ticker_move", "NVDA move")] },
      "/news/calendar?days=7": { as_of: ISO, available: true, econ: [], earnings: [] },
    });
    expect(await screen.findByText("CPI")).toBeInTheDocument();
    const box = screen.getByLabelText("Filter by symbol");
    for (const v of ["n", "nv", "nvd", "nvda"]) fireEvent.change(box, { target: { value: v } });
    expect(await screen.findByText("NVDA move")).toBeInTheDocument();
    const symbolCalls = () => apiFetchMock.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("symbol="));
    await waitFor(() => expect(symbolCalls()).toEqual(["/news/feed?symbol=NVDA&limit=30"]));
  });

  it("says the news service has not run yet when unavailable", async () => {
    renderWithQuery(<NewsFeed />, {
      "/news/feed?limit=30": { as_of: ISO, available: false, posts: [] },
      "/news/calendar?days=7": { as_of: ISO, available: false, econ: [], earnings: [] },
    });
    expect(await screen.findByText(/news service has not written anything yet/i)).toBeInTheDocument();
  });

  it("is a titled section whose chips are 'Show' and whose symbol field has a visible label", async () => {
    renderWithQuery(<NewsFeed />, { "/news/feed?limit=30": { as_of: ISO, available: true, posts: [] } });
    expect(screen.getByRole("heading", { level: 2, name: "Latest" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Show" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    const box = screen.getByLabelText("Filter by symbol");
    expect(box).not.toHaveAttribute("aria-label");
    expect(box).toHaveClass("min-h-11", "text-base");
  });

  it("says it is loading instead of showing an empty feed", () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><NewsFeed /></QueryClientProvider>);
    expect(screen.getByRole("status", { name: "Loading the news" })).toBeInTheDocument();
    expect(screen.queryByText(/No posts/)).toBeNull();
  });

  it("says a failed read in words, not as an empty feed", async () => {
    renderWithQuery(<NewsFeed />, {});
    expect(await screen.findByText("The news feed could not be loaded. It is asked for again every minute.")).toBeInTheDocument();
    expect(screen.queryByText(/No posts/)).toBeNull();
  });

  it("names the symbol when a filter matches nothing", async () => {
    renderWithQuery(<NewsFeed />, {
      "/news/feed?limit=30": { as_of: ISO, available: true, posts: [post(1, "macro_print", "CPI")] },
      "/news/feed?symbol=ZZZ&limit=30": { as_of: ISO, available: true, posts: [] },
    });
    expect(await screen.findByText("CPI")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by symbol"), { target: { value: "zzz" } });
    expect(await screen.findByText("No posts match ZZZ in this group.")).toBeInTheDocument();
  });
});
