import { screen, fireEvent } from "@testing-library/react";
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

  it("says the news service has not run yet when unavailable", async () => {
    renderWithQuery(<NewsFeed />, {
      "/news/feed?limit=30": { as_of: ISO, available: false, posts: [] },
      "/news/calendar?days=7": { as_of: ISO, available: false, econ: [], earnings: [] },
    });
    expect(await screen.findByText(/news service has not written anything yet/i)).toBeInTheDocument();
  });
});
