import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CheckRibbon } from "./CheckRibbon";

describe("CheckRibbon", () => {
  it("renders one segment per check", () => {
    render(<CheckRibbon category="health" passed={4} failed={1} unknown={1} total={6} />);
    expect(screen.getAllByTestId("segment")).toHaveLength(6);
  });

  it("distinguishes states by data attribute, not only by colour", () => {
    render(<CheckRibbon category="health" passed={4} failed={1} unknown={1} total={6} />);
    const states = screen.getAllByTestId("segment").map((s) => s.dataset.state);
    expect(states.filter((s) => s === "pass")).toHaveLength(4);
    expect(states.filter((s) => s === "fail")).toHaveLength(1);
    expect(states.filter((s) => s === "unknown")).toHaveLength(1);
  });

  it("gives the unknown segment a hatch texture so it is not colour-only", () => {
    render(<CheckRibbon category="health" passed={0} failed={0} unknown={6} total={6} />);
    expect(screen.getAllByTestId("segment")[0].className).toContain("hatch");
  });

  it("states the evaluable count, not just the pass count", () => {
    render(<CheckRibbon category="health" passed={3} failed={1} unknown={2} total={6} />);
    expect(screen.getByText(/3 of 4/)).toBeDefined();
    expect(screen.getByText(/2 unknown/)).toBeDefined();
  });

  it("does not claim a score out of the total when checks are unknown", () => {
    render(<CheckRibbon category="health" passed={3} failed={1} unknown={2} total={6} />);
    expect(screen.queryByText(/3 of 6/)).toBeNull();
  });

  it("renders a not-applicable category as a dimmed track with no score", () => {
    render(
      <CheckRibbon category="past" passed={0} failed={0} unknown={0} total={6} notApplicable />,
    );
    expect(screen.getByText(/not applicable/i)).toBeDefined();
    expect(screen.getAllByTestId("segment")[0].dataset.state).toBe("na");
  });

  it("exposes an accessible label carrying the counts", () => {
    render(<CheckRibbon category="value" passed={2} failed={3} unknown={1} total={6} />);
    const label = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(label).toContain("2 passed");
    expect(label).toContain("3 failed");
    expect(label).toContain("1 unknown");
  });
});