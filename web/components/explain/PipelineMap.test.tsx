import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PipelineMap } from "./PipelineMap";

describe("PipelineMap", () => {
  it("renders every main-pipeline stage plus the watching and web side nodes", () => {
    render(<PipelineMap active={null} onNavigate={() => {}} />);
    for (const label of [
      "Data In",
      "Finding Trades",
      "The Risk Gate",
      "Claude's Role",
      "Approval & Execution",
      "Watching & Adjusting",
      "This Dashboard",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeDefined();
    }
  });

  it("marks the active stage with aria-current", () => {
    render(<PipelineMap active="gate" onNavigate={() => {}} />);
    const gateBtn = screen.getByRole("button", { name: "The Risk Gate" });
    expect(gateBtn.getAttribute("aria-current")).toBe("step");
    const dataBtn = screen.getByRole("button", { name: "Data In" });
    expect(dataBtn.getAttribute("aria-current")).toBeNull();
  });

  it("calls onNavigate with the clicked stage's key", () => {
    const onNavigate = vi.fn();
    render(<PipelineMap active={null} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("button", { name: "Claude's Role" }));
    expect(onNavigate).toHaveBeenCalledWith("claude");
  });

  it("navigating to the web side node passes its key too", () => {
    const onNavigate = vi.fn();
    render(<PipelineMap active={null} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("button", { name: "This Dashboard" }));
    expect(onNavigate).toHaveBeenCalledWith("web");
  });
});
