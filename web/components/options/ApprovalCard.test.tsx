import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { ApprovalCard } from "./ApprovalCard";
import type { ApprovalSummary } from "./types";

afterEach(cleanup);
afterEach(() => {
  submitCommand.mockReset();
  confirmCommand.mockReset();
});

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function approval(overrides: Partial<ApprovalSummary> = {}): ApprovalSummary {
  return {
    as_of: "2026-09-06T12:00:00Z",
    id: 42,
    candidate_id: "c1",
    status: "pending",
    underlying: "NVDA",
    strategy: "cash_secured_put",
    right: "P",
    strike: 190.0,
    expiry: "2026-10-16",
    contracts: 2,
    premium: 3.25,
    blended_score: 72.0,
    expires_at: null,
    decided_at: null,
    order_state: null,
    source: "scan",
    ...overrides,
  };
}

const submitCommand = vi.fn();
const confirmCommand = vi.fn();
vi.mock("@/lib/commands", async () => {
  const actual = await vi.importActual("@/lib/commands");
  return {
    ...(actual as object),
    submitCommand: (...args: unknown[]) => submitCommand(...args),
    confirmCommand: (...args: unknown[]) => confirmCommand(...args),
  };
});

/** The dialog's confirm control — scoped to the dialog so it never matches
 * the card's own Approve button (same accessible name). */
function dialogConfirm() {
  const dialog = screen.getByRole("dialog");
  const buttons = dialog.querySelectorAll<HTMLButtonElement>("button");
  // Cancel is first, confirm is last.
  return buttons[buttons.length - 1];
}

describe("ApprovalCard — decide controls (M3)", () => {
  it("opens ConfirmAction before any request is made", () => {
    withClient(<ApprovalCard approval={approval()} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    // The dialog is open and shows the exact contract and contract count.
    const summary = screen.getByTestId("confirm-summary");
    expect(summary.textContent).toContain("2 contracts");
    expect(summary.textContent).toContain("NVDA");
    // No request has been made — the confirm step has not happened yet.
    expect(submitCommand).not.toHaveBeenCalled();
  });

  it("calls POST /commands once on confirm and renders a receipt from the id", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41,
      kind: "approve",
      status: "pending",
      result: null,
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
    withClient(<ApprovalCard approval={approval()} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(dialogConfirm());
    // Called once with the right kind and payload.
    await waitFor(() =>
      expect(submitCommand).toHaveBeenCalledTimes(1),
    );
    expect(submitCommand).toHaveBeenCalledWith("approve", { approval_id: 42 });
    // The receipt renders, driven by the returned id.
    expect(await screen.findByTestId("command-receipt")).toBeDefined();
    expect(screen.getByText(/intent 41/)).toBeDefined();
  });

  it("disables both controls while a command is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    submitCommand.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    withClient(<ApprovalCard approval={approval()} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(dialogConfirm());
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Reject" }) as HTMLButtonElement).disabled)
        .toBe(true),
    );
    resolve({
      id: 41, kind: "approve", status: "pending", result: null,
      needs_confirmation: false, confirm_token: null,
      created_at: "x", applied_at: null, as_of: "x", created: true,
    });
  });

  it("renders its decision, not action controls, for a decided approval", () => {
    withClient(<ApprovalCard approval={approval({ status: "rejected" })} />);
    expect(screen.getByTestId("approval-decision").textContent).toContain("rejected");
    expect(screen.queryByRole("button", { name: /approve|reject/i })).toBeNull();
  });

  it("renders a permission message on a 403, not a generic failure", async () => {
    submitCommand.mockRejectedValueOnce(new ApiError(403, "forbidden"));
    withClient(<ApprovalCard approval={approval()} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(dialogConfirm());
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByRole("alert").textContent).toContain("permission");
    expect(screen.getByRole("alert").textContent).not.toContain("could not be created");
  });

  it("renders a stalled receipt in words when the drain is unhealthy", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41, kind: "approve", status: "pending", result: null,
      needs_confirmation: false, confirm_token: null,
      created_at: "x", applied_at: null, as_of: "x", created: true,
    });
    withClient(<ApprovalCard approval={approval()} drainHealthy={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(dialogConfirm());
    const receipt = await screen.findByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("stalled");
    expect(
      screen.getAllByText("the trading service is not draining commands").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("reads the orders cache as an OrderListResponse, not a bare OrderSummary[]", async () => {
    // Regression: DecideControls used to read getQueryData<OrderSummary[]>
    // under ["options","orders"], but <OrdersTable/> caches an
    // OrderListResponse ({ as_of, orders: [...] }) there. A receipt could
    // never advance from `applied` to `submitted`/`filled` from the cache —
    // the .find() ran on the wrong shape and returned undefined.
    submitCommand.mockResolvedValueOnce({
      id: 41, kind: "approve", status: "applied", result: { decision: "Approved" },
      needs_confirmation: false, confirm_token: null,
      created_at: "x", applied_at: "x", as_of: "x", created: true,
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    // Seed the cache with the REAL shape OrdersTable stores.
    qc.setQueryData(["options", "orders"], {
      as_of: "x",
      orders: [
        {
          as_of: "x", id: 7, candidate_id: "c1", approval_id: 42,
          underlying: "NVDA", strategy: "cash_secured_put", strike: 190,
          expiry: "2026-10-16", state: "submitted", limit_price: 2.45,
          filled_qty: 0, avg_fill_price: null, is_live: false, detail: null,
          created_at: "x", updated_at: "x",
        },
      ],
    });
    render(
      <QueryClientProvider client={qc}>
        <ApprovalCard approval={approval()} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(dialogConfirm());
    // The receipt advances to `submitted` because the cache (with the right
    // shape) carries a working order for this approval. Before the fix it
    // stayed `applied` — the .find() returned undefined on the wrong shape.
    const receipt = await screen.findByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("submitted");
  });
});

describe("ApprovalCard — live-mode second confirmation (M3 3.5)", () => {
  it("renders the live step as a distinct, clearly labelled step, not a repeat", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41, kind: "approve", status: "pending", result: null,
      needs_confirmation: true, confirm_token: "tok-abc",
      created_at: "x", applied_at: null, as_of: "x", created: true,
    });
    confirmCommand.mockResolvedValueOnce(undefined);
    withClient(<ApprovalCard approval={approval()} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    const firstDialog = screen.getByRole("dialog");
    const firstCopy = firstDialog.textContent ?? "";
    fireEvent.click(dialogConfirm());

    // The live step opens: distinct copy, clearly labelled.
    const liveDialog = await screen.findByRole("dialog");
    expect(liveDialog.textContent).toContain("LIVE");
    // The live copy differs from the paper copy.
    expect(liveDialog.textContent).not.toBe(firstCopy);

    // Releasing it confirms via POST /commands/{id}/confirm.
    fireEvent.click(dialogConfirm());
    await waitFor(() => expect(confirmCommand).toHaveBeenCalledWith(41, "tok-abc"));
  });

  it("keeps the command pending (needs_confirmation) if the live step is cancelled", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41, kind: "approve", status: "pending", result: null,
      needs_confirmation: true, confirm_token: "tok-abc",
      created_at: "x", applied_at: null, as_of: "x", created: true,
    });
    withClient(<ApprovalCard approval={approval()} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(dialogConfirm());
    await screen.findAllByText(/LIVE/);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(confirmCommand).not.toHaveBeenCalled();
    // The intent exists but stays pending-unconfirmed, stated in the receipt.
    const receipt = await screen.findByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("queued");
  });
});