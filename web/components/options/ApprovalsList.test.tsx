import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalsList } from "./ApprovalsList";

afterEach(cleanup);
afterEach(() => submitCommand.mockReset());

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const submitCommand = vi.fn();
vi.mock("@/lib/commands", async () => {
  const actual = await vi.importActual("@/lib/commands");
  return {
    ...(actual as object),
    submitCommand: (...args: unknown[]) => submitCommand(...args),
  };
});

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

  it("does not flash 'stalled' before the controls query resolves", async () => {
    // Regression: ApprovalsList used to default drain_healthy to `false` while
    // the controls query was loading, so every receipt flashed `stalled`
    // ("the trading service is not draining commands") on first render with
    // no evidence the drain was actually dead. The default is now `true` (no
    // evidence = assume healthy); `stalled` requires a real unhealthy report.
    const { apiFetch } = await import("@/lib/api");
    let resolveControls: (v: unknown) => void = () => {};
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.includes("/options/controls")) {
        return new Promise((r) => (resolveControls = r));
      }
      return Promise.resolve({
        as_of: "x",
        approvals: [
          {
            as_of: "x", id: 1, candidate_id: "c1", status: "pending",
            underlying: "NVDA", strategy: "cash_secured_put", right: "P",
            strike: 190.0, expiry: "2026-10-16", contracts: 1, premium: 3.25,
            blended_score: 72.0, expires_at: null, decided_at: null,
            order_state: null, source: "scan",
          },
        ],
      });
    });
    withClient(<ApprovalsList />);
    await screen.findByText(/NVDA/);
    // While controls are still pending, no receipt has been created yet (no
    // command has been submitted). The list itself must NOT render any
    // "stalled" text — that would be a false alarm with no evidence.
    expect(screen.queryByText("the trading service is not draining commands")).toBeNull();
    // Release the controls query as unhealthy — NOW stalled is honest.
    resolveControls({
      as_of: "x", autonomy: { level: "manual", label: "Manual" }, rungs: [],
      halted: false, halt_reason: null, mode: "paper",
      drain_healthy: false, drain_last_seen: null, pending_commands: 0,
    });
  });
});

describe("ApprovalsList — filter and submitted-tab plumbing (moving a card off Approve)", () => {
  function twoApprovals() {
    return {
      as_of: "x",
      approvals: [
        {
          as_of: "x", id: 1, candidate_id: "c1", status: "pending",
          underlying: "NVDA", strategy: "cash_secured_put", right: "P",
          strike: 190.0, expiry: "2026-10-16", contracts: 1, premium: 3.25,
          blended_score: 72.0, created_at: "2026-09-01T00:00:00Z",
          expires_at: null, decided_at: null, order_state: null, source: "scan",
        },
        {
          as_of: "x", id: 2, candidate_id: "c2", status: "pending",
          underlying: "AAPL", strategy: "covered_call", right: "C",
          strike: 230.0, expiry: "2026-10-16", contracts: 1, premium: 2.10,
          blended_score: 60.0, created_at: "2026-09-01T00:00:00Z",
          expires_at: null, decided_at: null, order_state: null, source: "scan",
        },
      ],
    };
  }

  it("applies an optional filter so a caller can show only a subset", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue(twoApprovals());
    withClient(<ApprovalsList filter={(a) => a.id === 2} />);
    await screen.findByText(/AAPL/);
    expect(screen.queryByText(/NVDA/)).toBeNull();
  });

  it("renders a custom empty-state message when given one", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", approvals: [] });
    withClient(<ApprovalsList emptyText="No approvals submitted yet." />);
    expect(await screen.findByText("No approvals submitted yet.")).toBeDefined();
  });

  it("fires onApprovalSubmitted the moment Approve is confirmed", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41, kind: "approve", status: "pending", result: null,
      needs_confirmation: false, confirm_token: null,
      created_at: "x", applied_at: null, as_of: "x", created: true,
    });
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue(twoApprovals());
    const onApprovalSubmitted = vi.fn();
    withClient(<ApprovalsList onApprovalSubmitted={onApprovalSubmitted} />);
    await screen.findByText(/NVDA/);
    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    fireEvent.click(approveButtons[0]);
    const dialog = screen.getByRole("dialog");
    const buttons = dialog.querySelectorAll<HTMLButtonElement>("button");
    fireEvent.click(buttons[buttons.length - 1]);
    await screen.findByTestId("command-receipt");
    expect(onApprovalSubmitted).toHaveBeenCalledWith(1, expect.objectContaining({ id: 41 }));
  });
});

describe("ApprovalsList — status prop (Rejected/Expired tab)", () => {
  it("defaults to fetching only pending approvals", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", approvals: [] });
    withClient(<ApprovalsList />);
    await screen.findByText(/No pending approvals/i);
    expect(apiFetch).toHaveBeenCalledWith("/options/approvals?status=pending");
  });

  it("fetches every status when status='all' is passed", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", approvals: [] });
    withClient(<ApprovalsList status="all" emptyText="Nothing decided yet." />);
    await screen.findByText(/Nothing decided yet/i);
    expect(apiFetch).toHaveBeenCalledWith("/options/approvals?status=all");
  });
});