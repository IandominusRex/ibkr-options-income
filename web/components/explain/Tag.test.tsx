import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Tag } from "./Tag";

describe("Tag", () => {
  it("renders its text", () => {
    render(<Tag>Stage 1</Tag>);
    expect(screen.getByText("Stage 1")).toBeDefined();
  });

  it("defaults to the neutral tone", () => {
    render(<Tag>Neutral</Tag>);
    expect(screen.getByText("Neutral").className).toContain("text-muted");
  });

  it("applies the tone's colour class", () => {
    render(<Tag tone="positive">Safe</Tag>);
    expect(screen.getByText("Safe").className).toContain("text-gain");
  });
});
