import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { OPEN_SEARCH_EVENT } from "@/lib/search";
import { ResearchPage } from "./ResearchPage";

const served = {
  "/value/top": { as_of: "x", available: true, list_name: "deep_value", items: [] },
  "/watchlist": { as_of: "x", items: [] },
  "/research/sectors": { as_of: "x", sectors: [] },
};

describe("ResearchPage", () => {
  it("is titled Research, with a line saying what the page holds", () => {
    renderWithQuery(<ResearchPage />, served);
    expect(screen.getByRole("heading", { level: 1, name: "Research" })).toBeInTheDocument();
    expect(screen.getByText("What the value book would buy, the names you follow, and how each sector is doing.")).toBeInTheDocument();
  });

  it("opens the console's one search palette instead of mounting its own", () => {
    renderWithQuery(<ResearchPage />, served);
    const seen = vi.fn();
    window.addEventListener(OPEN_SEARCH_EVENT, seen);
    const search = screen.getByRole("button", { name: "Search" });
    expect(search).toHaveAttribute("data-variant", "secondary");
    fireEvent.click(search);
    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("links to Universe, the scan's own lists", () => {
    renderWithQuery(<ResearchPage />, served);
    expect(screen.getAllByRole("link", { name: "Universe" })[0]).toHaveAttribute("href", "/research/universe");
  });

  it("puts Top opportunities first, then Your watchlist, then the Sectors card, which is the phone's order", async () => {
    renderWithQuery(<ResearchPage />, served);
    const top = screen.getByRole("heading", { level: 2, name: "Top opportunities" });
    const watch = await screen.findByRole("heading", { level: 2, name: "Your watchlist" });
    const sectors = screen.getByRole("heading", { level: 2, name: "Sectors by IV rank" });
    const follows = (a: Element, b: Element) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(follows(top, watch)).toBe(true);
    expect(follows(watch, sectors)).toBe(true);
    expect(screen.getByRole("group", { name: "Opportunity list" })).toBeInTheDocument();
  });

  it("sizes both columns to one minmax(0,1fr) track, so a wide row never widens the page on a phone", async () => {
    renderWithQuery(<ResearchPage />, served);
    const watch = await screen.findByRole("heading", { level: 2, name: "Your watchlist" });
    expect(watch.closest("section")?.parentElement).toHaveClass("grid-cols-1", "min-w-0");
    const sectors = screen.getByRole("heading", { level: 2, name: "Sectors by IV rank" });
    expect(sectors.closest("section")?.parentElement).toHaveClass("grid-cols-1", "min-w-0");
  });
});
