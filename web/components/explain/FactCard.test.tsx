import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FactCard } from "./FactCard";

describe("FactCard", () => {
  it("renders the tag, title, and body", () => {
    render(
      <FactCard tag="Feasibility" tone="info" title="Cash reserve comes off first">
        20% of available cash.
      </FactCard>,
    );
    expect(screen.getByText("Feasibility")).toBeDefined();
    expect(screen.getByText("Cash reserve comes off first")).toBeDefined();
    expect(screen.getByText("20% of available cash.")).toBeDefined();
  });
});
