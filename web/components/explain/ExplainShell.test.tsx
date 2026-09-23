import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExplainShell } from "./ExplainShell";

describe("ExplainShell", () => {
  it("opens on the Overview panel", () => {
    render(<ExplainShell />);
    expect(screen.getByRole("heading", { name: "The system, in one pass" })).toBeDefined();
  });

  it("switches panels via the tab bar", () => {
    render(<ExplainShell />);
    fireEvent.click(screen.getByRole("button", { name: "Gate" }));
    expect(screen.getByRole("heading", { name: "The risk gate" })).toBeDefined();
    expect(screen.queryByRole("heading", { name: "The system, in one pass" })).toBeNull();
  });

  it("marks the active tab bar entry with aria-current", () => {
    render(<ExplainShell />);
    fireEvent.click(screen.getByRole("button", { name: "Claude" }));
    expect(screen.getByRole("button", { name: "Claude" }).getAttribute("aria-current")).toBe(
      "page",
    );
  });

  it("navigates from an overview card straight into that panel", () => {
    render(<ExplainShell />);
    // The overview grid renders a card per subtab using the full label; "The Risk Gate"
    // card is distinct from the "Gate" tab-bar button and the pipeline-map box, so this
    // exercises the onNavigate prop threading through OverviewPanel rather than the tab bar.
    fireEvent.click(screen.getAllByRole("button", { name: "The Risk Gate" })[0]);
    expect(screen.getByRole("heading", { name: "The risk gate" })).toBeDefined();
  });

  it("navigates via a ties-into chip on a subtab", () => {
    render(<ExplainShell />);
    fireEvent.click(screen.getByRole("button", { name: "Gate" }));
    // GatePanel ties into "execution" — click that chip and land on the execution panel.
    const executionTie = screen
      .getAllByRole("button")
      .find((el) => el.textContent?.includes("Approval & Execution") && el.textContent?.includes("live quote"));
    expect(executionTie).toBeDefined();
    fireEvent.click(executionTie!);
    expect(screen.getByRole("heading", { name: "Approval & execution" })).toBeDefined();
  });
});
