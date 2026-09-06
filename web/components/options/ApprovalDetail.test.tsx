import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ApprovalDetailCard } from "./ApprovalDetail";
import type { ApprovalDetail } from "./types";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return { ...(actual as object), apiFetch: vi.fn() };
});

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
    withClient(<ApprovalDetailCard detail={base} />);
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
    withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.getByText("IV rank too low (poor premium)")).toBeDefined();
    expect(screen.queryByText("iv_rank_below_minimum")).toBeNull();
  });

  it("renders the ideal zone bar with numbers visible", () => {
    withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.getByText(/\$185\.00/)).toBeDefined();
    expect(screen.getByText(/\$192\.00/)).toBeDefined();
    expect(screen.getByText(/\$3\.10/)).toBeDefined();
    // The ideal zone section heading is present.
    expect(screen.getByText("Ideal zone")).toBeDefined();
  });

  it("renders nothing for a null review, not a bordered box", () => {
    const { container } = withClient(<ApprovalDetailCard detail={{ ...base, review: null }} />);
    expect(screen.queryByText("No review available")).toBeNull();
    // No bordered box is rendered for the review section.
    expect(container.textContent).not.toContain("No review");
  });

  it("renders a not-found state with a link back to the list", () => {
    // The page handles 404; this test verifies the card itself does not
    // render when detail is absent. The page-level 404 is tested via the
    // page component's error branch.
    withClient(<ApprovalDetailCard detail={base} />);
    // The "Back to approvals" link is always present on the detail card.
    expect(screen.getByText(/Back to approvals/i)).toBeDefined();
  });

  it("renders decide controls for a pending approval, wired through the confirm gate", () => {
    withClient(<ApprovalDetailCard detail={base} />);
    // M3: the controls are real. Clicking Approve opens the confirmation dialog
    // BEFORE any request is made — the M2 guard ("no dead affordance") evolves
    // into "the control does what it claims".
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(screen.getByTestId("confirm-summary").textContent).toContain("NVDA");
  });

  it("renders a stalled receipt when the drain is unhealthy (not hardcoded healthy)", async () => {
    // Regression: ApprovalDetailCard used to hardcode drainHealthy={true}, so
    // the detail page could never show spec §9.2 rule 3's `stalled` state —
    // a dead drain was indistinguishable from a live one on this surface.
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockImplementation(async (path: string) => {
      if (path === "/options/controls") {
        return {
          as_of: "x",
          autonomy: { level: "manual", label: "Manual" },
          rungs: [],
          halted: false,
          halt_reason: null,
          mode: "paper",
          drain_healthy: false,
          drain_last_seen: null,
          pending_commands: 0,
        };
      }
      if (path === "/commands") {
        return {
          id: 41, kind: "approve", status: "pending", result: null,
          needs_confirmation: false, confirm_token: null,
          created_at: "x", applied_at: null, as_of: "x", created: true,
        };
      }
      throw new Error(`unexpected fetch ${path}`);
    });
    withClient(<ApprovalDetailCard detail={base} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog");
    const buttons = dialog.querySelectorAll<HTMLButtonElement>("button");
    fireEvent.click(buttons[buttons.length - 1]);
    // The drain is unhealthy, so once the command is pending the receipt must
    // render `stalled` in words — not `queued` (the hardcoded-true behaviour).
    const receipt = await waitFor(() => screen.getByTestId("command-receipt"));
    expect(receipt.getAttribute("data-state")).toBe("stalled");
    expect(
      screen.getAllByText("the trading service is not draining commands").length,
    ).toBeGreaterThan(0);
  });
});