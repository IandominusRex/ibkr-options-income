import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Callout } from "./Callout";

describe("Callout", () => {
  it("renders the label and children", () => {
    render(<Callout label="No AI involved">Deterministic Python only.</Callout>);
    expect(screen.getByText("No AI involved")).toBeDefined();
    expect(screen.getByText("Deterministic Python only.")).toBeDefined();
  });

  it("defaults to the info tone", () => {
    render(<Callout label="Note">text</Callout>);
    expect(screen.getByText("Note").className).toContain("text-focus");
  });

  it("colours the label per tone, distinctly from every other tone", () => {
    const { rerender } = render(
      <Callout label="Guarantee" tone="positive">
        text
      </Callout>,
    );
    expect(screen.getByText("Guarantee").className).toContain("text-gain");

    rerender(
      <Callout label="Careful" tone="caution">
        text
      </Callout>,
    );
    expect(screen.getByText("Careful").className).toContain("text-unknown");
  });
});
