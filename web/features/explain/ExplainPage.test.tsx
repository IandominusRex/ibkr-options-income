import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PAGES } from "@/features/search/pages";
import { ExplainPage, PARTS } from "./ExplainPage";

describe("ExplainPage", () => {
  it("is titled How it works, with seven sections in a fixed order", () => {
    render(<ExplainPage />);
    expect(screen.getByRole("heading", { level: 1, name: "How it works" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "A day, from scan to order",
      "Who decides what",
      "Four books in one account",
      "Sizing and the market",
      "Rolls, assignment and freeing cash",
      "What keeps it safe",
      "Where to look",
    ]);
  });

  it("links only to pages the console has (every link is in the search palette's page list)", () => {
    const known = new Set(PAGES.map((p) => p.href));
    for (const part of PARTS) for (const w of part.where) expect(known.has(w.href), w.href).toBe(true);
    render(<ExplainPage />);
    expect(screen.getAllByRole("link", { name: "Trades" })[0]).toHaveAttribute("href", "/trades");
  });

  it("states the core rule and both written exceptions as Claude's limits, not as Claude trading", () => {
    const { container } = render(<ExplainPage />);
    const text = container.textContent ?? "";
    expect(text).toContain("it is the only path to an order");
    expect(text).toContain("It never places, prices or gates an order");
    expect(text).toContain("Claude may lower, never raise, the contract count");
    expect(text).toContain("only recorded in live");
    expect(text).toContain("the console never sends an order itself");
  });

  it("uses no em dash and none of the banned words", () => {
    const { container } = render(<ExplainPage />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("—");
    expect(text).not.toMatch(/seamless|robust|unlock|elevate/i);
  });

  it("makes each link a 44px row on a phone", () => {
    render(<ExplainPage />);
    for (const link of screen.getAllByRole("link")) expect(link).toHaveClass("min-h-11", "md:min-h-0");
  });
});
