import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ApprovalsList } from "./ApprovalsList";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("ApprovalsList", () => {
  it("renders the empty state when there are no approvals", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", approvals: [] });
    withClient(<ApprovalsList />);
    expect(await screen.findByText(/No pending approvals/i)).toBeDefined();
  });

  it("renders a card for each approval", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      approvals: [
        {
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
        },
      ],
    });
    withClient(<ApprovalsList />);
    expect(await screen.findByText(/NVDA/)).toBeDefined();
    expect(screen.getByText(/\$3\.25\/sh/)).toBeDefined();
  });

  it("renders review fields separately when present", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      approvals: [
        {
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
          review: {
            why_attractive: "Rich IV rank.",
            risks: "Earnings risk.",
            tradeoffs: "",
            assignment_considerations: "",
            rolling_considerations: "",
          },
        },
      ],
    });
    withClient(<ApprovalsList />);
    expect(await screen.findByText(/Rich IV rank/)).toBeDefined();
    expect(screen.getByText(/Earnings risk/)).toBeDefined();
  });

  it("renders action controls for pending approvals, wired — not dead affordances", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      approvals: [
        {
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
        },
      ],
    });
    withClient(<ApprovalsList />);
    await screen.findByText(/NVDA/);
    // M3: the controls are real now. Clicking Approve opens the confirmation
    // dialog BEFORE any request is made — the M2 guard ("no dead control")
    // evolves into "the control does what it claims, through the confirm gate".
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(screen.getByTestId("confirm-summary").textContent).toContain("NVDA");
  });
});