import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApprovalDetailCard } from "./ApprovalDetail";
import type { ApprovalDetail } from "./types";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const nav = vi.hoisted(() => ({ params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.params }));

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
  created_at: "2026-09-01T08:30:00Z",
  expires_at: null,
  decided_at: null,
  order_state: null,
  source: "scan",
  review: {
    why_attractive: "Rich IV rank.",
    risks: "Earnings risk.",
    tradeoffs: "Higher strike raises assignment risk.",
    assignment_considerations: "Assignment at $190 is acceptable.",
    rolling_considerations: "Roll if delta approaches -0.40.",
  },
  snapshot: {},
  ideal: { lo: 185.0, hi: 192.0, min_credit: 3.1 },
  gate_reasons: ["IV rank too low (poor premium)"],
  alternatives: [],
  order_id: null,
  fills: [],
};

describe("ApprovalDetailCard", () => {
  beforeEach(() => {
    nav.params = new URLSearchParams();
  });

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

  it("renders no Fills section when there are none", () => {
    withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.queryByText("Fills")).toBeNull();
  });

  it("renders the approval-to-fill lineage when fills exist", () => {
    withClient(
      <ApprovalDetailCard
        detail={{
          ...base,
          order_id: 7,
          fills: [
            {
              as_of: "x",
              id: 1,
              order_id: 7,
              candidate_id: "c1",
              action: "SELL",
              filled_qty: 1,
              avg_price: 3.2,
              commission: 0.65,
              is_live: false,
              filled_at: "2026-09-01T09:00:00Z",
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("Fills")).toBeDefined();
    expect(screen.getByText("SELL")).toBeDefined();
    expect(screen.getByText("$3.20")).toBeDefined();
  });

  it("renders a not-found state with a link back to the list", () => {
    // The page handles 404; this test verifies the card itself does not
    // render when detail is absent. The page-level 404 is tested via the
    // page component's error branch.
    withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.getByRole("link", { name: "Back to Trades" })).toHaveAttribute("href", "/trades");
  });

  it("goes back to the Trades view, day and strategy it was opened from, and nothing else", () => {
    nav.params = new URLSearchParams("view=history&day=2026-11-03&strategy=csp&x=1");
    withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.getByRole("link", { name: "Back to Trades" })).toHaveAttribute(
      "href",
      "/trades?view=history&day=2026-11-03&strategy=csp",
    );
  });

  it("goes to plain Trades for an unreadable day, or with nothing to return to", () => {
    nav.params = new URLSearchParams("day=junk");
    const { unmount } = withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.getByRole("link", { name: "Back to Trades" })).toHaveAttribute("href", "/trades");
    unmount();
    nav.params = new URLSearchParams();
    withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.getByRole("link", { name: "Back to Trades" })).toHaveAttribute("href", "/trades");
  });

  it("titles the page with the contract and its status in words", () => {
    withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.getByRole("heading", { level: 1, name: "NVDA · Sell $190 put" })).toBeDefined();
    expect(screen.getByText("Pending")).toBeDefined();
  });

  it("sums the trade in a stub and labels the review as Claude's", () => {
    withClient(<ApprovalDetailCard detail={base} />);
    expect(screen.getByRole("group", { name: "NVDA put math" })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Claude's review" })).toBeDefined();
  });

  it("says who decided it, from the record, and what it filled at", () => {
    withClient(
      <ApprovalDetailCard
        detail={{ ...base, status: "approved", decided_at: "2026-10-16T19:03:40Z", decided_by: "system", order_state: "filled", fill_price: 3.2 }}
      />,
    );
    expect(screen.getByText("Approved by the system")).toBeDefined();
    expect(screen.getByText("Filled at")).toBeDefined();
    expect(screen.getByText("$3.20")).toBeDefined();
  });

  it("says only Approved when who decided was not recorded", () => {
    withClient(<ApprovalDetailCard detail={{ ...base, status: "approved", decided_at: "2026-10-01T15:00:00Z" }} />);
    expect(screen.getByText("Approved")).toBeDefined();
    expect(screen.queryByText(/by the system|by you/)).toBeNull();
  });

  it("a roll shows both legs and the net it was priced at", () => {
    const roll = {
      ...base,
      source: "roll" as const,
      strategy: "roll",
      strike: 190,
      expiry: "2026-10-30",
      premium: 1.175,
      roll_from: { strike: 190, expiry: "2026-10-23", right: "P", contracts: 1, old_mid: 2.1, new_mid: 3.275 },
    };
    withClient(<ApprovalDetailCard detail={roll} />);
    expect(screen.getByRole("heading", { level: 1, name: "NVDA · Roll $190 put Oct 23 → Oct 30" })).toBeDefined();
    const stub = screen.getByRole("group", { name: "NVDA roll math" });
    expect(stub.textContent).toMatch(/Buy back \$190 put Oct 23/);
    expect(stub.textContent).toMatch(/Net credit/);
    expect(screen.getByText(/At the quotes it was priced at/)).toBeDefined();
  });

  describe("what a filled roll filled at", () => {
    const rollOf = (net: number, fill: number): ApprovalDetail => ({
      ...base,
      status: "approved",
      decided_by: "system",
      order_state: "filled",
      source: "roll",
      strategy: "roll",
      strike: 190,
      expiry: "2026-10-30",
      premium: net,
      fill_price: fill,
      roll_from: { strike: 190, expiry: "2026-10-23", right: "P", contracts: 1, old_mid: 2.1, new_mid: 3.275 },
    });
    const valueOf = (label: string) => screen.getByText(label).nextElementSibling?.textContent;

    it("reads as a signed net, labelled so it cannot pass for a single-leg price", () => {
      withClient(<ApprovalDetailCard detail={rollOf(0.45, 0.45)} />);
      expect(valueOf("Net filled, a share")).toBe("+$0.45");
      expect(valueOf("Net a share, as priced")).toBe("+$0.45");
      expect(screen.queryByText("Filled at")).toBeNull();
    });

    it("writes a debit roll with the minus sign, never $-0.30", () => {
      withClient(<ApprovalDetailCard detail={rollOf(-0.3, -0.3)} />);
      expect(valueOf("Net filled, a share")).toBe("−$0.30");
      expect(valueOf("Net a share, as priced")).toBe("−$0.30");
      expect(document.body.textContent).not.toMatch(/\$-/);
    });

    it("leaves a flat fill as $0", () => {
      withClient(<ApprovalDetailCard detail={rollOf(0, 0)} />);
      expect(valueOf("Net filled, a share")).toBe("$0");
    });

    it("keeps a single-leg order's own price under Filled at", () => {
      withClient(<ApprovalDetailCard detail={{ ...base, status: "approved", order_state: "filled", fill_price: 3.2 }} />);
      expect(valueOf("Filled at")).toBe("$3.20");
    });
  });

  it("puts the decision after the trade and the review, the phone's order", () => {
    withClient(<ApprovalDetailCard detail={base} />);
    const trade = screen.getByRole("heading", { name: "The trade" });
    const review = screen.getByRole("heading", { name: "Claude's review" });
    const decision = screen.getByRole("heading", { name: "Decision" });
    const follows = (a: Element, b: Element) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(follows(trade, review)).toBe(true);
    expect(follows(review, decision)).toBe(true);
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