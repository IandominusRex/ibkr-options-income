import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { NewsPage } from "./NewsPage";

const ISO = "2026-11-07T01:00:00Z";
// /claude/context is left unmocked on purpose: the Market card then shows its failure sentence, which is
// enough to place it in the page's order without a full market picture fixture.
const served = {
  "/news/feed": { as_of: ISO, available: true, posts: [] },
  "/news/calendar": { as_of: ISO, available: true, econ: [], earnings: [] },
};

describe("NewsPage", () => {
  it("is titled News, with a line saying what the page holds and that nothing here trades", () => {
    renderWithQuery(<NewsPage />, served);
    expect(screen.getByRole("heading", { level: 1, name: "News" })).toBeInTheDocument();
    expect(
      screen.getByText("What moved, what is scheduled this week, and what the news service made of it. Nothing here trades."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh the news" })).toBeInTheDocument();
  });

  it("puts the Market card first, then the feed, which is the phone's order", async () => {
    renderWithQuery(<NewsPage />, served);
    const market = await screen.findByText(/The market picture could not be loaded/);
    const feed = screen.getByRole("heading", { level: 2, name: "Latest" });
    expect(market.compareDocumentPosition(feed) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("uses the frame's single-track columns, so a wide card never widens the page", () => {
    const { container } = renderWithQuery(<NewsPage />, served);
    const grid = container.querySelector(".lg\\:grid-cols-\\[minmax\\(0\\,1fr\\)_340px\\]");
    expect(grid).not.toBeNull();
    for (const col of Array.from(grid!.children)) expect(col).toHaveClass("grid", "min-w-0", "grid-cols-1");
  });
});
