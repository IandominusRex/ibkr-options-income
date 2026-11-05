import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { loadPersistedCommand } from "@/lib/commands";
import { AnalyseButton } from "./AnalyseButton";

const submitCommand = vi.fn();
vi.mock("@/lib/commands", async () => {
  const actual = await vi.importActual("@/lib/commands");
  return { ...(actual as object), submitCommand: (...args: unknown[]) => submitCommand(...args) };
});

afterEach(() => {
  cleanup();
  submitCommand.mockReset();
  localStorage.clear();
});

function cmd(over: Record<string, unknown> = {}) {
  return {
    id: 9, kind: "value_analyse", status: "pending", result: null, needs_confirmation: false, confirm_token: null,
    created_at: "2026-11-05T12:00:00Z", applied_at: null, as_of: "2026-11-05T12:00:00Z", created: true, ...over,
  };
}

function showButton(extra: Record<string, unknown> = {}) {
  return renderWithQuery(<AnalyseButton symbol="GOOGL" />, { "/commands/9": cmd(), ...extra });
}

describe("AnalyseButton", () => {
  it("sends one value_analyse for the symbol with no confirmation, and follows it with a receipt", async () => {
    submitCommand.mockResolvedValue(cmd());
    showButton();
    fireEvent.click(await screen.findByRole("button", { name: "Run Claude's analysis" }));
    await waitFor(() => expect(submitCommand).toHaveBeenCalledTimes(1));
    expect(submitCommand).toHaveBeenCalledWith("value_analyse", { symbol: "GOOGL" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await screen.findByTestId("command-receipt")).toBeInTheDocument();
  });

  it("disables the button while the command is in flight and keeps it across a reload", async () => {
    submitCommand.mockResolvedValue(cmd());
    showButton();
    const button = await screen.findByRole("button", { name: "Run Claude's analysis" });
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await waitFor(() => expect(loadPersistedCommand("value-analyse:GOOGL")?.id).toBe(9));
  });

  it("says Claude's reads are off in config when the value process answers claude_off", async () => {
    submitCommand.mockResolvedValue(cmd());
    showButton({ "/commands/9": cmd({ status: "failed", result: { reason: "claude_off" } }) });
    fireEvent.click(await screen.findByRole("button", { name: "Run Claude's analysis" }));
    expect(await screen.findByText("Claude's reads are off in config.")).toBeInTheDocument();
  });

  it("says the read is queued, and that the block refreshes, once the command applies", async () => {
    submitCommand.mockResolvedValue(cmd());
    showButton({ "/commands/9": cmd({ status: "applied", result: { symbol: "GOOGL", queued: true } }) });
    fireEvent.click(await screen.findByRole("button", { name: "Run Claude's analysis" }));
    expect(await screen.findByText(/Claude's read is queued/)).toBeInTheDocument();
  });

  it("says nothing was queued when the request itself is refused", async () => {
    const { ApiError } = await import("@/lib/api");
    submitCommand.mockRejectedValue(new ApiError(403, "forbidden"));
    showButton();
    fireEvent.click(await screen.findByRole("button", { name: "Run Claude's analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have permission to do this. Nothing was queued.");
  });

  it("never puts Claude's words on the button, and it is not the lime control", async () => {
    showButton();
    const button = await screen.findByRole("button", { name: "Run Claude's analysis" });
    expect(button).toHaveAttribute("data-variant", "secondary");
  });
});
