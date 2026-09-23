import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { HaltControl } from "./HaltControl";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
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

afterEach(cleanup);
afterEach(() => {
  submitCommand.mockReset();
  confirmCommand.mockReset();
});

function appliedCommand(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    kind: "halt",
    status: "applied",
    result: { halted: true, reason: "x" },
    needs_confirmation: false,
    confirm_token: null,
    created_at: "2026-09-07T10:00:00Z",
    applied_at: "2026-09-07T10:00:02Z",
    as_of: "2026-09-07T10:00:02Z",
    ...overrides,
  };
}

/** The confirmation weights are the specification; each test name states why. */

describe("HaltControl", () => {
  it("halt is a single click with no dialog: the command fires immediately", async () => {
    submitCommand.mockResolvedValue(appliedCommand({ kind: "halt" }));
    withClient(
      <HaltControl halted={false} haltReason={null} haltedAt={null} />,
    );

    const halt = screen.getByTestId("halt-button");
    fireEvent.click(halt);

    await waitFor(() => expect(submitCommand).toHaveBeenCalledTimes(1));
    expect(submitCommand).toHaveBeenCalledWith("halt", {});
    // No dialog ever appeared for the halt itself.
    expect(screen.queryByTestId("confirm-dialog")).toBeNull();
  });

  it("resume requires the typed word and stays disabled until it matches exactly", async () => {
    submitCommand.mockResolvedValue(appliedCommand({ kind: "resume", result: { halted: false } }));
    withClient(
      <HaltControl halted={true} haltReason="spread blew out" haltedAt="2026-09-07T09:59:00Z" />,
    );

    fireEvent.click(screen.getByTestId("resume-button"));
    const dialog = screen.getByTestId("confirm-dialog");
    expect(dialog).toBeTruthy();

    // The confirm control inside the dialog (scoped: the trigger is also "Resume").
    const confirm = within(dialog).getByRole("button", { name: "Resume" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    // A case-mismatched or partial word must stay disabled.
    fireEvent.change(within(dialog).getByLabelText(/Type RESUME to confirm/i), {
      target: { value: "resume" },
    });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(within(dialog).getByLabelText(/Type RESUME to confirm/i), {
      target: { value: "RESUME" },
    });
    expect((confirm as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(confirm);
    await waitFor(() =>
      expect(submitCommand).toHaveBeenCalledWith("resume", {}),
    );
  });

  it("resume is not one click: no command before the typed word", () => {
    withClient(
      <HaltControl halted={true} haltReason="x" haltedAt="2026-09-07T09:59:00Z" />,
    );
    fireEvent.click(screen.getByTestId("resume-button"));
    expect(submitCommand).not.toHaveBeenCalled();
  });

  it("the halted state shows the reason and the time as text", () => {
    withClient(
      <HaltControl halted={true} haltReason="spread blew out" haltedAt="2026-09-07T09:59:00Z" />,
    );
    const box = screen.getByTestId("halt-control");
    expect(box.textContent).toContain("spread blew out");
    expect(box.textContent).toContain("halted");
  });

  it("an unknown halt time renders honest words, not a fabricated time", () => {
    withClient(<HaltControl halted={true} haltReason="breaker" haltedAt={null} />);
    expect(screen.getByTestId("halt-control").textContent).toContain("unknown time");
  });

  it("a 403 renders a permission message, not a generic failure", async () => {
    submitCommand.mockRejectedValue(new ApiError(403, "forbidden"));
    withClient(<HaltControl halted={false} haltReason={null} haltedAt={null} />);
    fireEvent.click(screen.getByTestId("halt-button"));
    await waitFor(() =>
      expect(screen.getByTestId("command-error").textContent).toContain(
        "do not have permission",
      ),
    );
    expect(screen.queryByTestId("command-receipt")).toBeNull();
  });

  it("the control is disabled while its command is in flight and shows a receipt", async () => {
    submitCommand.mockResolvedValue(
      appliedCommand({ status: "pending", applied_at: null }),
    );
    withClient(<HaltControl halted={false} haltReason={null} haltedAt={null} />);
    fireEvent.click(screen.getByTestId("halt-button"));

    await waitFor(() => expect(screen.getByTestId("command-receipt")).toBeTruthy());
    expect((screen.getByTestId("halt-button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("a drain-dead state is stated in words beside the control through the receipt", async () => {
    submitCommand.mockResolvedValue(
      appliedCommand({ status: "pending", applied_at: null }),
    );
    withClient(
      <HaltControl halted={false} haltReason={null} haltedAt={null} drainHealthy={false} />,
    );
    fireEvent.click(screen.getByTestId("halt-button"));
    await waitFor(() => expect(screen.getByTestId("command-receipt")).toBeTruthy());
    // The receipt itself carries the stalled words (CommandReceipt's tested
    // behaviour); here we assert the strip renders it, not just colour.
    expect(screen.getByTestId("command-receipt").getAttribute("data-state")).toBe(
      "stalled",
    );
  });

  it("a live-mode second confirmation routes through ConfirmAction and is released", async () => {
    submitCommand.mockResolvedValue(
      appliedCommand({
        status: "pending",
        needs_confirmation: true,
        confirm_token: "tok",
      }),
    );
    confirmCommand.mockResolvedValue(undefined);
    withClient(<HaltControl halted={false} haltReason={null} haltedAt={null} />);

    fireEvent.click(screen.getByTestId("halt-button"));
    await waitFor(() => expect(screen.getByTestId("confirm-dialog")).toBeTruthy());
    expect(screen.getByTestId("confirm-dialog").textContent).toContain("LIVE");

    fireEvent.click(screen.getByRole("button", { name: /Release halt intent/i }));
    await waitFor(() => expect(confirmCommand).toHaveBeenCalledWith(7, "tok"));
  });

  it("cancelling the live step leaves the intent queued and unconfirmed", async () => {
    submitCommand.mockResolvedValue(
      appliedCommand({
        status: "pending",
        needs_confirmation: true,
        confirm_token: "tok",
      }),
    );
    withClient(<HaltControl halted={false} haltReason={null} haltedAt={null} />);

    fireEvent.click(screen.getByTestId("halt-button"));
    await waitFor(() => expect(screen.getByTestId("confirm-dialog")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(confirmCommand).not.toHaveBeenCalled();
    expect(screen.getByTestId("command-receipt").getAttribute("data-state")).toBe(
      "queued",
    );
  });

  it("disables Resume while the live confirmation dialog is open, before it is released", async () => {
    // Regression: `inFlight` used to ignore `liveStep`, leaving Resume
    // clickable during the window between the first confirm and the live
    // release — there is no command id to poll yet in that window.
    submitCommand.mockResolvedValue(
      appliedCommand({
        kind: "resume",
        status: "pending",
        needs_confirmation: true,
        confirm_token: "tok",
      }),
    );
    withClient(<HaltControl halted={true} haltReason={null} haltedAt={null} />);
    fireEvent.click(screen.getByTestId("resume-button"));
    // The confirm button stays disabled until "RESUME" is typed exactly.
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "RESUME" } });
    const resumeDialog = screen.getByTestId("confirm-dialog");
    fireEvent.click(within(resumeDialog).getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(screen.getByTestId("confirm-dialog")).toBeTruthy());
    expect(
      (screen.getByTestId("resume-button") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("uses a hyphen, never an em dash, for the halt reason", () => {
    withClient(<HaltControl halted={true} haltReason="drawdown" haltedAt={null} />);
    expect(screen.getByText(/- drawdown/)).toBeDefined();
  });
});

describe("HaltControl — reload persistence (localStorage)", () => {
  it("restores an in-flight receipt from localStorage on a fresh mount", async () => {
    const { savePersistedCommand } = await import("@/lib/commands");
    savePersistedCommand("halt-resume", appliedCommand({ status: "pending" }));
    withClient(<HaltControl halted={false} haltReason={null} haltedAt={null} />);
    expect(await screen.findByTestId("command-receipt")).toBeDefined();
    expect((screen.getByTestId("halt-button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("restores the live second-confirmation dialog from localStorage on a fresh mount", async () => {
    const { savePersistedCommand } = await import("@/lib/commands");
    savePersistedCommand(
      "halt-resume",
      appliedCommand({ status: "pending", needs_confirmation: true, confirm_token: "tok" }),
    );
    withClient(<HaltControl halted={false} haltReason={null} haltedAt={null} />);
    const dialog = await screen.findByTestId("confirm-dialog");
    expect(dialog.textContent).toContain("LIVE");
  });
});