import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConfirmAction } from "./ConfirmAction";

afterEach(cleanup);

function renderDialog(overrides: Partial<Parameters<typeof ConfirmAction>[0]> = {}) {
  const props = {
    title: "Approve NVDA 190 put",
    summary: (
      <span>
        Sell 2 contracts of NVDA 2026-10-16 190 put at $3.25 per share ($650 total)
      </span>
    ),
    confirmLabel: "Approve",
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  render(<ConfirmAction {...props} />);
  return props;
}

describe("ConfirmAction", () => {
  it("shows the exact contract and contract count in the summary", () => {
    renderDialog();
    const summary = screen.getByTestId("confirm-summary");
    // The summary content is rendered, not summarised away.
    expect(summary.textContent).toContain("2 contracts");
    expect(summary.textContent).toContain("NVDA 2026-10-16 190 put");
    expect(summary.textContent).toContain("$3.25 per share");
  });

  it("is a labelled, aria-modal dialog", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    // Labelled: the heading is inside the dialog and associated via aria-labelledby.
    const labelledBy = dialog.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    expect(dialog.querySelector(`#${labelledBy}`)).not.toBeNull();
    expect(screen.getByText("Approve NVDA 190 put")).toBeDefined();
  });

  it("calls onConfirm when the confirm control is clicked", () => {
    const props = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(props.onConfirm).toHaveBeenCalledTimes(1);
  });

  it("Escape and the cancel control both call onCancel", () => {
    const props = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(props.onCancel).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onCancel).toHaveBeenCalledTimes(2);
  });

  it("traps Tab within the dialog while open", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    const buttons = dialog.querySelectorAll<HTMLElement>("button");
    // Focus starts inside the dialog (on the cancel control).
    expect(document.activeElement).toBe(buttons[0]);
    // Tab from the LAST focusable wraps to the FIRST.
    buttons[buttons.length - 1].focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(buttons[0]);
    // Shift+Tab from the FIRST wraps to the LAST.
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(buttons[buttons.length - 1]);
  });

  it("returns focus to the trigger on close", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Open approve";
    document.body.appendChild(trigger);
    trigger.focus();
    const { unmount } = render(
      <ConfirmAction
        title="Approve NVDA 190 put"
        summary="s"
        confirmLabel="Confirm"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    unmount();
    expect(document.activeElement).toBe(trigger);
    document.body.removeChild(trigger);
  });

  describe("requireTypedWord", () => {
    it("keeps confirm disabled until the word matches exactly", () => {
      renderDialog({ requireTypedWord: "HALT" });
      const confirm = screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement;
      expect(confirm.disabled).toBe(true);
      // Wrong case does not match — the gate is case-sensitive.
      const input = screen.getByRole("textbox");
      fireEvent.change(input, { target: { value: "halt" } });
      expect(confirm.disabled).toBe(true);
      fireEvent.change(input, { target: { value: "HALT" } });
      expect(confirm.disabled).toBe(false);
    });
  });
});