import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Tile, TileList } from "./Tile";

describe("Tile", () => {
  it("is a labelled figure line with its test id", () => {
    render(
      <TileList testId="list">
        <Tile id="total" label="Total profit" value="$2,575.84" tone="text-gain" />
      </TileList>,
    );
    const line = screen.getByTestId("tile-total");
    expect(line).toHaveTextContent("Total profit");
    expect(line).toHaveTextContent("$2,575.84");
    expect(screen.getByText("$2,575.84")).toHaveClass("text-gain");
    expect(screen.getByTestId("list").tagName).toBe("DL");
  });
  it("draws an unknown figure as a hatched n/a", () => {
    render(
      <TileList>
        <Tile id="contributed" label="Contributed capital" value="n/a" tone="text-unknown" />
      </TileList>,
    );
    expect(screen.getByText("n/a")).toHaveClass("hatch");
  });
});
