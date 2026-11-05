import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { loadPersistedCommand } from "@/lib/commands";
import { ValueDecide } from "./ValueDecide";
import type { ValueProposalLike } from "./types";

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

afterEach(() => {
  cleanup();
  submitCommand.mockReset();
  confirmCommand.mockReset();
  localStorage.clear();
});

const buy: ValueProposalLike = {
  id: 5, kind: "buy", symbol: "AAPL", shares: 20, price: 182.4, cause: "python", status: "pending", fingerprint: "abc123def0",
};

function cmd(over: Record<string, unknown> = {}) {
  return {
    id: 9, kind: "value_approve", status: "pending", result: null, needs_confirmation: false, confirm_token: null,
    created_at: "2026-11-05T12:00:00Z", applied_at: null, as_of: "2026-11-05T12:00:00Z", created: true, ...over,
  };
}

function show(p: ValueProposalLike = buy, responses: Record<string, unknown> = {}) {
  return renderWithQuery(<ValueDecide proposal={p} releaseMaxCloses={2} />, { "/commands/9": cmd(), ...responses });
}

describe("ValueDecide", () => {
  it("opens the confirmation before any request, and a buy's sentence names the release it may cause", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(submitCommand).not.toHaveBeenCalled();
    const summary = screen.getByTestId("confirm-summary");
    expect(summary.textContent).toContain(
      "Approving lets the system buy 20 shares of AAPL at its next check, sized at the close of $182.40, at the mid of a fresh quote. " +
        "If cash is short it may close up to 2 of your wheel's cash-secured puts at breakeven or better to fund it.",
    );
  });
  it("says only Claude's number makes the sale when the cause is Claude", () => {
    show({ ...buy, kind: "sell", cause: "claude", price: null });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByTestId("confirm-summary").textContent).toContain("Only Claude's number makes this sale");
  });
  it("sends exactly one value_approve with the proposal id and fingerprint on confirm", async () => {
    submitCommand.mockResolvedValue(cmd());
    show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(submitCommand).toHaveBeenCalledTimes(1));
    expect(submitCommand).toHaveBeenCalledWith("value_approve", { proposal_id: 5, fingerprint: "abc123def0" });
  });
  it("sends value_reject for Reject", async () => {
    submitCommand.mockResolvedValue(cmd({ kind: "value_reject" }));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(screen.getByTestId("confirm-summary").textContent).toContain("will not buy 20 shares of AAPL");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(submitCommand).toHaveBeenCalledWith("value_reject", { proposal_id: 5, fingerprint: "abc123def0" }));
    expect(submitCommand).toHaveBeenCalledTimes(1);
  });
  it("cancelling sends nothing", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(submitCommand).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("follows the command with a receipt and disables both buttons while it is in flight", async () => {
    submitCommand.mockResolvedValue(cmd());
    show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByTestId("command-receipt")).toHaveTextContent("intent 9");
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });
  it("tells a stale card to be refreshed in the words the task names", async () => {
    submitCommand.mockResolvedValue(cmd());
    show(buy, { "/commands/9": cmd({ status: "failed", result: { reason: "stale_proposal" } }) });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("This card is out of date; refresh it.")).toBeInTheDocument();
  });
  it("says nothing has been sent once approved, because the order goes out at the next check", async () => {
    submitCommand.mockResolvedValue(cmd());
    show(buy, { "/commands/9": cmd({ status: "applied", result: { ok: true } }) });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/Nothing has been sent yet/)).toBeInTheDocument();
  });
  it("keeps an in-flight command across a reload under the key value:<proposal id>", async () => {
    submitCommand.mockResolvedValue(cmd());
    const first = show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    await screen.findByTestId("command-receipt");
    await waitFor(() => expect(loadPersistedCommand("value:5")?.id).toBe(9));
    expect(localStorage.getItem("ibkr-options:command:value:5")).not.toBeNull();
    first.unmount();
    show();
    expect(await screen.findByTestId("command-receipt")).toHaveTextContent("intent 9");
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  });
  it("asks for the second confirmation when the API holds the intent (live), and releases it on confirm", async () => {
    submitCommand.mockResolvedValue(cmd({ needs_confirmation: true, confirm_token: "tok" }));
    confirmCommand.mockResolvedValue(undefined);
    show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    const live = await screen.findByText(/Confirm LIVE value_approve/);
    expect(live).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Release value_approve intent" }));
    await waitFor(() => expect(confirmCommand).toHaveBeenCalledWith(9, "tok"));
  });
  it("keeps the live second confirmation across a reload (the held intent is restored)", async () => {
    submitCommand.mockResolvedValue(cmd({ needs_confirmation: true, confirm_token: "tok" }));
    const first = show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    await screen.findByText(/Confirm LIVE value_approve/);
    await waitFor(() => expect(loadPersistedCommand("value:5")?.confirm_token).toBe("tok"));
    first.unmount();
    show();
    expect(await screen.findByText(/Confirm LIVE value_approve/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Release value_approve intent" })).toBeInTheDocument();
    expect(confirmCommand).not.toHaveBeenCalled();
  });
  it("cancelling the live step keeps the receipt for the held intent and releases nothing", async () => {
    submitCommand.mockResolvedValue(cmd({ needs_confirmation: true, confirm_token: "tok" }));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    await screen.findByText(/Confirm LIVE value_approve/);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/Confirm LIVE value_approve/)).toBeNull();
    expect(await screen.findByTestId("command-receipt")).toHaveTextContent("intent 9");
    expect(confirmCommand).not.toHaveBeenCalled();
  });
  it("shows the decision, not the buttons, once the proposal is no longer pending", () => {
    show({ ...buy, status: "approved" });
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByText(/Decision: approved/)).toBeInTheDocument();
  });
  it("reports a failed request in words and sends nothing further", async () => {
    submitCommand.mockRejectedValue(new Error("boom"));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The command could not be created. Nothing was sent.");
    expect(screen.getByRole("button", { name: "Approve" })).not.toBeDisabled();
  });
});
