import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DegradedNotice } from "./DegradedNotice";

describe("DegradedNotice", () => {
  it("carries the backend's note verbatim", () => {
    render(<DegradedNotice note="Values are from the last end-of-day run." />);
    expect(
      screen.getByText("Values are from the last end-of-day run."),
    ).toBeInTheDocument();
  });

  it("composes no explanation of its own beyond the note text", () => {
    const { container } = render(<DegradedNotice note="Custom degraded-state note." />);
    expect(container.textContent).toBe("Custom degraded-state note.");
  });

  it("reads as a notice, not an error - no loss colour", () => {
    const { container } = render(<DegradedNotice note="A note." />);
    expect(container.querySelector(".text-loss")).toBeNull();
  });
});
