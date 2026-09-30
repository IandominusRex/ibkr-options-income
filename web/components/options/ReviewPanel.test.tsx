import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReviewPanel } from "./ReviewPanel";
import type { ClaudeReviewPayload } from "./types";

const FULL_REVIEW: ClaudeReviewPayload = {
  recommendation: "approve",
  confidence: 0.75,
  why_attractive: "Rich IV rank.",
  risks: "Earnings risk.",
  tradeoffs: "Breakeven is close.",
  assignment_considerations: "Delta suggests low probability.",
  rolling_considerations: "Roll up if it breaches the strike.",
};

describe("ReviewPanel", () => {
  it("renders nothing for a null review", () => {
    const { container } = render(<ReviewPanel review={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders every present field as a card with its own tag and text, distinct from the others", () => {
    render(<ReviewPanel review={FULL_REVIEW} />);
    expect(screen.getByText("Why attractive")).toBeDefined();
    expect(screen.getByText("Bull case")).toBeDefined();
    expect(screen.getByText("Rich IV rank.")).toBeDefined();

    expect(screen.getByText("Risks")).toBeDefined();
    expect(screen.getByText("Bear case")).toBeDefined();
    expect(screen.getByText("Earnings risk.")).toBeDefined();

    expect(screen.getByText("Tradeoffs")).toBeDefined();
    expect(screen.getByText("Assignment considerations")).toBeDefined();
    expect(screen.getByText("Rolling considerations")).toBeDefined();
  });

  it("only renders cards for fields that actually have text", () => {
    render(
      <ReviewPanel
        review={{ ...FULL_REVIEW, tradeoffs: "", rolling_considerations: "" }}
      />,
    );
    expect(screen.getByText("Why attractive")).toBeDefined();
    expect(screen.queryByText("Tradeoffs")).toBeNull();
    expect(screen.queryByText("Rolling considerations")).toBeNull();
  });

  it("renders nothing when every field is empty", () => {
    const { container } = render(
      <ReviewPanel
        review={{
          recommendation: "wait",
          confidence: 0.5,
          why_attractive: "",
          risks: "",
          tradeoffs: "",
          assignment_considerations: "",
          rolling_considerations: "",
        }}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("leads with the plain-English summary as the verdict", () => {
    render(
      <ReviewPanel
        review={{ ...FULL_REVIEW, recommendation: "wait", summary: "Wait for the export ruling." }}
      />,
    );
    expect(screen.getByText("Summary")).toBeDefined();
    expect(screen.getByText("Verdict: wait")).toBeDefined();
    expect(screen.getByText("Wait for the export ruling.")).toBeDefined();
  });

  it("lists cited evidence ids with the kind of source each one is", () => {
    render(<ReviewPanel review={{ ...FULL_REVIEW, evidence: ["F3", "N11"] }} />);
    expect(screen.getByText("F3")).toBeDefined();
    expect(screen.getByText("computed fact")).toBeDefined();
    expect(screen.getByText("N11")).toBeDefined();
    expect(screen.getByText("news headline")).toBeDefined();
  });

  it("renders a summary-only review instead of nothing", () => {
    render(
      <ReviewPanel
        review={{
          why_attractive: "",
          risks: "",
          tradeoffs: "",
          assignment_considerations: "",
          rolling_considerations: "",
          summary: "Sell - nothing inside the window argues against it.",
        }}
      />,
    );
    expect(screen.getByText("Sell - nothing inside the window argues against it.")).toBeDefined();
  });

  it("shows no evidence line for a review stored before evidence existed", () => {
    render(<ReviewPanel review={FULL_REVIEW} />);
    expect(screen.queryByText("Cited:")).toBeNull();
  });
});
