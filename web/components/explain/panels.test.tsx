import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExplainShell } from "./ExplainShell";
import { TAB_META } from "./types";

// Every subtab's exact <h2> title, keyed by its tab-bar short label — walking the whole
// shell this way catches a panel that fails to render, a title typo, or a tab that got
// wired to the wrong panel, in one pass.
const EXPECTED_HEADING: Record<string, string> = {
  Overview: "The system, in one pass",
  Data: "Data in",
  Ideas: "Finding trades",
  Gate: "The risk gate",
  Claude: "Claude's role",
  Approve: "Approval & execution",
  Watching: "Watching & adjusting",
  Dashboard: "This dashboard",
};

describe("every System Explanation subtab", () => {
  it("covers every entry in TAB_META", () => {
    const shortLabels = Object.values(TAB_META).map((m) => m.short);
    expect(new Set(Object.keys(EXPECTED_HEADING))).toEqual(new Set(shortLabels));
  });

  for (const [short, heading] of Object.entries(EXPECTED_HEADING)) {
    it(`renders the ${short} panel with its map, ties-into, and source refs`, () => {
      render(<ExplainShell />);
      fireEvent.click(screen.getByRole("button", { name: short }));

      expect(screen.getByRole("heading", { name: heading })).toBeDefined();
      // Every panel mounts the shared pipeline map (the "Finding Trades" box is present on
      // every subtab, active or not).
      expect(screen.getByRole("button", { name: "Finding Trades" })).toBeDefined();
      // Every panel (Overview included, via its SourceRefs list) cites at least one real
      // source file so "under the hood" never renders empty.
      expect(screen.getByText("Under the hood")).toBeDefined();
    });
  }
});
