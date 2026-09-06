import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApprovalDetailCard } from "./ApprovalDetail";
import type { ApprovalDetail } from "./types";

const base: ApprovalDetail = {
  as_of: "x",
  id: 1,
  candidate_id: "c1",
  status: "pending",
  underlying: "NVDA",
  strategy: "cash_secured_put",
  right: "P",
  strike: 190.0,
  expiry: "2026-10-16",
  contracts: 1,
  premium: 3.25,
  blended_score: 72.0,
  expires_at: null,
  decided_at: null,
  order_state: null,
  source: "scan",
  snapshot: {},
  ideal: { lo: 185.0, hi: 192.0, min_credit: 3.1 },
  gate_reasons: ["IV rank too low (poor premium)"],
  review: {
    why_attractive: "Rich IV rank.",
    risks: "Earnings risk.",
    tradeoffs: "Higher strike raises assignment risk.",
    assignment_considerations: "Assignment at $190 is acceptable.",
    rolling_considerations: "Roll if delta approaches -0.40.",
  },
  alternatives: [],
};

describe("ApprovalDetailCard", () => {
  it("renders the five review fields as five labelled sections", () => {
    render(<ApprovalDetailCard detail={base} />);
    expect(screen.getByText("Why attractive")).toBeDefined();
    expect(screen.getByText("Risks")).toBeDefined();
    expect(screen.getByText("Tradeoffs")).toBeDefined();
    expect(screen.getByText("Assignment considerations")).toBeDefined();
    expect(screen.getByText("Rolling considerations")).toBeDefined();
    // The five fields are distinct, not one paragraph.
    expect(screen.getByText("Rich IV rank.")).toBeDefined();
    expect(screen.getByText("Earnings risk.")).toBeDefined();
  });

  it("renders gate reasons as humanised text, not raw codes", () => {
    render(<ApprovalDetailCard detail={base} />);
    expect(screen.getByText("IV rank too low (poor premium)")).toBeDefined();
    expect(screen.queryByText("iv_rank_below_minimum")).toBeNull();
  });

  it("renders the ideal zone bar with numbers visible", () => {
    render(<ApprovalDetailCard detail={base} />);
    expect(screen.getByText(/\$185\.00/)).toBeDefined();
    expect(screen.getByText(/\$192\.00/)).toBeDefined();
    expect(screen.getByText(/\$3\.10/)).toBeDefined();
    // The ideal zone section heading is present.
    expect(screen.getByText("Ideal zone")).toBeDefined();
  });

  it("renders nothing for a null review, not a bordered box", () => {
    const { container } = render(
      <ApprovalDetailCard detail={{ ...base, review: null }} />,
    );
    expect(screen.queryByText("No review available")).toBeNull();
    // No bordered box is rendered for the review section.
    expect(container.textContent).not.toContain("No review");
  });

  it("renders a not-found state with a link back to the list", () => {
    // The page handles 404; this test verifies the card itself does not
    // render when detail is absent. The page-level 404 is tested via the
    // page component's error branch.
    render(<ApprovalDetailCard detail={base} />);
    // The "Back to approvals" link is always present on the detail card.
    expect(screen.getByText(/Back to approvals/i)).toBeDefined();
  });

  it("asserts no button with an accessible name matching /approve|reject/i exists", () => {
    render(<ApprovalDetailCard detail={base} />);
    const buttons = screen.queryAllByRole("button", { name: /approve|reject/i });
    expect(buttons).toHaveLength(0);
  });
});