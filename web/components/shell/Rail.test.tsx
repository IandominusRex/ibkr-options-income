import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RailSection } from "./RailSection";

describe("RailSection", () => {
  it("renders an available section as a link", () => {
    render(<RailSection sectionKey="research" label="Research" available note={null} />);
    expect(screen.getByRole("link", { name: /research/i })).toBeDefined();
  });

  it("renders an unavailable section as disabled with its reason", () => {
    render(
      <RailSection sectionKey="options" label="Options" available={false} note="Arrives in P2" />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Arrives in P2")).toBeDefined();
  });

  it("marks an unavailable section aria-disabled rather than hiding it", () => {
    render(<RailSection sectionKey="pnl" label="P&L" available={false} note="Arrives in P4" />);
    expect(screen.getByRole("listitem").getAttribute("aria-disabled")).toBe("true");
  });
});