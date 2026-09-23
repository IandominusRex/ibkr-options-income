import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RangeBar } from "./RangeBar";

describe("RangeBar", () => {
  it("renders its label, bounds, and scale endpoints", () => {
    render(
      <RangeBar
        label="CSP delta target"
        lowPct={15}
        highPct={30}
        lowText="0.15"
        highText="0.30"
        scaleLeft="0.0 (deep OTM)"
        scaleRight="1.0 (deep ITM)"
      />,
    );
    expect(screen.getByText("CSP delta target")).toBeDefined();
    expect(screen.getByText("0.15")).toBeDefined();
    expect(screen.getByText("0.30")).toBeDefined();
    expect(screen.getByText("0.0 (deep OTM)")).toBeDefined();
    expect(screen.getByText("1.0 (deep ITM)")).toBeDefined();
  });

  it("renders the filled range at the given bounds, not animated in", () => {
    const { container } = render(
      <RangeBar
        label="DTE window"
        lowPct={12}
        highPct={47}
        lowText="7d"
        highText="28d"
        scaleLeft="0d"
        scaleRight="60d"
      />,
    );
    const fill = container.querySelector(".border-focus") as HTMLElement;
    expect(fill.style.left).toBe("12%");
    expect(fill.style.right).toBe("53%");
  });
});
