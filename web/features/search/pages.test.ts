import { describe, expect, it, vi } from "vitest";
import { OPEN_SEARCH_EVENT, openSearch } from "@/lib/search";
import { PAGES, matchPages } from "./pages";

describe("matchPages", () => {
  it("finds nothing for a blank term", () => {
    expect(matchPages("")).toEqual([]);
    expect(matchPages("   ")).toEqual([]);
  });

  it("puts a page whose name starts with the term first", () => {
    expect(matchPages("trad").map((p) => p.label).slice(0, 2)).toEqual(["Trades", "Trades, History"]);
  });

  it("matches a page's words, not only its name", () => {
    expect(matchPages("regime").map((p) => p.href)).toEqual(["/more/claude"]);
  });

  it("needs every word typed, in any order", () => {
    expect(matchPages("ledger activity").map((p) => p.href)).toEqual(["/activity?view=ledger"]);
  });

  it("ignores case and lists at most five", () => {
    expect(matchPages("ACTIVITY").length).toBeLessThanOrEqual(5);
    expect(matchPages("a").length).toBe(5);
  });

  it("links only to routes the console has, and never to a write", () => {
    const routes = ["/", "/trades", "/portfolio", "/activity", "/research", "/research/universe", "/news", "/more", "/more/claude", "/explain", "/ledger/import"];
    for (const p of PAGES) expect(routes).toContain(p.href.split("?")[0]);
    expect(new Set(PAGES.map((p) => p.href)).size).toBe(PAGES.length);
  });

  it("carries no em dash in a label or a hint", () => {
    for (const p of PAGES) expect(`${p.label} ${p.hint}`).not.toContain("—");
  });
});

describe("openSearch", () => {
  it("dispatches the one event the palette listens for", () => {
    const seen = vi.fn();
    window.addEventListener(OPEN_SEARCH_EVENT, seen);
    openSearch();
    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
