import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AssessedRow } from "./AssessedRow";
import type { AssessedContract } from "./types";

afterEach(cleanup);
afterEach(() => {
  submitCommand.mockReset();
  confirmCommand.mockReset();
});

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function contract(overrides: Partial<AssessedContract> = {}): AssessedContract {
  return {
    as_of: "2026-09-06T12:00:00Z",
    candidate_id: "c1",
    symbol: "NVDA",
    strategy: "cash_secured_put",
    strike: 185.0,
    expiry: "2026-10-16",
    stage: "top_n",
    reasons: [],
    reasons_text: [],
    blended_score: 72.0,
    premium: 3.25,
    ideal: null,
    promotable: true,
    promote_note: null,
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
 * the row's own Promote button (same accessible name in the "Promote"
 * dialog case). Cancel is first, confirm is last. */
function dialogConfirm() {
  const dialog = screen.getByRole("dialog");
  const buttons = dialog.querySelectorAll<HTMLButtonElement>("button");
  return buttons[buttons.length - 1];
}

describe("AssessedRow — the promote control (M4 4.3)", () => {
  it("renders a promote control when the row is promotable", () => {
    withClient(<AssessedRow contract={contract()} />);
    expect(screen.getByRole("button", { name: "Promote" })).toBeDefined();
  });

  it("renders no promote control, disabled or otherwise, for a non-promotable risk_gate row", () => {
    withClient(
      <AssessedRow
        contract={contract({
          stage: "risk_gate",
          promotable: false,
          promote_note: "The Rules Engine rejected this contract.",
        })}
      />,
    );
    expect(screen.getByText(/Rules Engine rejected/i)).toBeDefined();
    expect(screen.queryAllByRole("button", { name: /promote/i })).toHaveLength(0);
  });

  it("renders no promote control when promotable is true but strike is unexpectedly null", () => {
    withClient(<AssessedRow contract={contract({ strike: null })} />);
    expect(screen.queryAllByRole("button", { name: /promote/i })).toHaveLength(0);
  });

  it("renders no promote control when promotable is true but expiry is unexpectedly null", () => {
    withClient(<AssessedRow contract={contract({ expiry: null })} />);
    expect(screen.queryAllByRole("button", { name: /promote/i })).toHaveLength(0);
  });

  it("opens ConfirmAction before any request is made", () => {
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(submitCommand).not.toHaveBeenCalled();
  });

  it("explains in the dialog that a promote reprices and regates, and only then produces an approval", () => {
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    const summary = screen.getByTestId("confirm-summary").textContent ?? "";
    expect(summary).toMatch(/price/i);
    expect(summary).toMatch(/Rules Engine/i);
    expect(summary).toMatch(/only if it still passes/i);
    // House style: no em dashes, no banned words.
    expect(summary).not.toContain("—");
    for (const banned of ["seamless", "robust", "unlock", "elevate"]) {
      expect(summary.toLowerCase()).not.toContain(banned);
    }
  });

  it("a score_floor row's confirmation additionally shows the score and the configured minimum", () => {
    withClient(
      <AssessedRow
        contract={contract({
          stage: "score_floor",
          blended_score: 50.0,
          promote_note: "Scores below your configured minimum of 55.0.",
        })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    const summary = screen.getByTestId("confirm-summary").textContent ?? "";
    expect(summary).toContain("50.0");
    expect(summary).toContain("55.0");
  });

  it("does not show the score/minimum addendum for a non-score_floor row", () => {
    withClient(<AssessedRow contract={contract({ stage: "top_n", blended_score: 72.0 })} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    const summary = screen.getByTestId("confirm-summary").textContent ?? "";
    expect(summary).not.toContain("72.0");
  });

  it("calls POST /commands with kind=promote exactly once on confirm, with the candidate fields", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41,
      kind: "promote",
      status: "pending",
      result: null,
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    fireEvent.click(dialogConfirm());
    await waitFor(() => expect(submitCommand).toHaveBeenCalledTimes(1));
    expect(submitCommand).toHaveBeenCalledWith("promote", {
      candidate_id: "c1",
      symbol: "NVDA",
      strategy: "cash_secured_put",
      strike: 185.0,
      expiry: "2026-10-16",
    });
    expect(await screen.findByTestId("command-receipt")).toBeDefined();
    expect(screen.getByText(/intent 41/)).toBeDefined();
  });

  it("disables the promote control while a command is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    submitCommand.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    fireEvent.click(dialogConfirm());
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Promote" }) as HTMLButtonElement).disabled).toBe(
        true,
      ),
    );
    resolve({
      id: 41,
      kind: "promote",
      status: "pending",
      result: null,
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
  });

  it("renders a permission message on a 403, not a generic failure", async () => {
    submitCommand.mockRejectedValueOnce(new ApiError(403, "forbidden"));
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    fireEvent.click(dialogConfirm());
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByRole("alert").textContent).toContain("permission");
  });

  it("renders failed with the humanised reason, and gate_rejected's reason codes through the same humaniser", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41,
      kind: "promote",
      status: "failed",
      result: {
        reason: "gate_rejected",
        detail: { reasons: ["delta_out_of_range", "dte_out_of_range"] },
      },
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: "x",
      as_of: "x",
      created: true,
    });
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    fireEvent.click(dialogConfirm());
    const receipt = await screen.findByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("failed");
    expect(receipt.textContent).toContain("gate rejected");
    expect(receipt.textContent).toContain("delta out of range");
    expect(receipt.textContent).toContain("dte out of range");
  });

  it("on success (applied) the receipt links to the new approval", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41,
      kind: "promote",
      status: "applied",
      result: { approval_id: 99 },
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: "x",
      as_of: "x",
      created: true,
    });
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    fireEvent.click(dialogConfirm());
    await screen.findByTestId("command-receipt");
    const link = (await screen.findByRole("link", { name: /view approval/i })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/options/99");
  });

  it("does not render a 'view approval' link when applied carries no approval_id", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41,
      kind: "promote",
      status: "applied",
      result: { approval_id: null, note: "order_already_active" },
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: "x",
      as_of: "x",
      created: true,
    });
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    fireEvent.click(dialogConfirm());
    await screen.findByTestId("command-receipt");
    expect(screen.queryByRole("link", { name: /view approval/i })).toBeNull();
  });
});

describe("AssessedRow — live-mode second confirmation (M4 4.3, mirrors M3 3.5)", () => {
  it("renders the live step as a distinct, clearly labelled step, not a repeat", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41,
      kind: "promote",
      status: "pending",
      result: null,
      needs_confirmation: true,
      confirm_token: "tok-abc",
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
    confirmCommand.mockResolvedValueOnce(undefined);
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    const firstDialog = screen.getByRole("dialog");
    const firstCopy = firstDialog.textContent ?? "";
    fireEvent.click(dialogConfirm());

    const liveDialog = await screen.findByRole("dialog");
    expect(liveDialog.textContent).toContain("LIVE");
    expect(liveDialog.textContent).not.toBe(firstCopy);

    fireEvent.click(dialogConfirm());
    await waitFor(() => expect(confirmCommand).toHaveBeenCalledWith(41, "tok-abc"));
  });

  it("keeps the command pending (needs_confirmation) if the live step is cancelled", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41,
      kind: "promote",
      status: "pending",
      result: null,
      needs_confirmation: true,
      confirm_token: "tok-abc",
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
    withClient(<AssessedRow contract={contract()} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    fireEvent.click(dialogConfirm());
    await screen.findAllByText(/LIVE/);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(confirmCommand).not.toHaveBeenCalled();
    const receipt = await screen.findByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("queued");
  });
});

describe("AssessedRow — drain health (mirrors ApprovalCard)", () => {
  it("renders a stalled receipt in words when the drain is unhealthy", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 41,
      kind: "promote",
      status: "pending",
      result: null,
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
    withClient(<AssessedRow contract={contract()} drainHealthy={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote" }));
    fireEvent.click(dialogConfirm());
    const receipt = await screen.findByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("stalled");
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
});
