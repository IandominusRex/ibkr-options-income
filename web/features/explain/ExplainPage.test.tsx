import { existsSync } from "node:fs";
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
      "Three books in one account",
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

  it("says what a halt covers, who sizes, how a release is approved and how the value fair value is made", () => {
    const { container } = render(<ExplainPage />);
    const text = container.textContent ?? "";
    expect(text).toContain(
      "A halt from the console stops new wheel and value-book orders until you lift it; credit spreads have their own halt.",
    );
    expect(text).toContain(
      "Python sets every size; Claude can only lower the count of a put the system opens on its own, as above.",
    );
    expect(text).toContain("from SPY, QQQ and the VIX");
    expect(text).toContain("on Home, Trades and News");
    expect(text).toContain(
      "That buy can follow a Ready that Claude's verdict decided, and a release needs no tap of its own: it inherits the buy's approval. Python checks every step twice, and the close never pays more than the entry credit less the required profit.",
    );
    expect(text).toContain(
      "with its fair value worked out by Python from Claude's inputs and capped at one and a half times Python's own",
    );
    expect(text).not.toContain("Every size is Python's.");
  });

  it("uses no em dash and none of the banned words", () => {
    const { container } = render(<ExplainPage />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("—");
    expect(text).not.toMatch(/seamless|robust|unlock|elevate/i);
  });

  it("replaces the eight-tab explainer, which is gone, and the search list describes the new page", () => {
    // vitest runs from web/, so this is web/components/explain.
    expect(existsSync("components/explain")).toBe(false);
    expect(PAGES.find((p) => p.href === "/explain")?.hint).toBe("The system in plain English");
  });

  it("makes each link a 44px row on a phone", () => {
    render(<ExplainPage />);
    for (const link of screen.getAllByRole("link")) expect(link).toHaveClass("min-h-11", "md:min-h-0");
  });
});
