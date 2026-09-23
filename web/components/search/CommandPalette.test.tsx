import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { CommandPalette } from "./CommandPalette";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(async () => ({
    as_of: "2026-09-02T00:00:00Z",
    query: "AAP",
    results: [
      { symbol: "AAP", name: "Advance Auto Parts", exchange: "NYSE", is_etf: false },
      { symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false },
    ],
  })),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

describe("CommandPalette", () => {
  beforeEach(() => push.mockClear());

  it("is closed until the shortcut fires", () => {
    render(<CommandPalette />);
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
  });

  it("opens on meta+k", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
  });

  it("shows results and navigates on select", async () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "AAP" } });
    await waitFor(() => expect(screen.getByText("Apple Inc.")).toBeDefined());
    fireEvent.click(screen.getByText("Apple Inc."));
    expect(push).toHaveBeenCalledWith("/stock/AAPL");
  });

  it("renders as a labelled dialog", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.hasAttribute("aria-labelledby")).toBe(true);
  });

  it("clears the search term and results on reopen, not stale from last time", async () => {
    // Regression: the component never unmounts on close (it renders `null`,
    // not a conditional mount), so term/hits used to persist across a
    // close/reopen — reopening showed the previous search.
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "AAP" } });
    await waitFor(() => expect(screen.getByText("Apple Inc.")).toBeDefined());

    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    expect((screen.getByPlaceholderText(/search/i) as HTMLInputElement).value).toBe("");
    expect(screen.queryByText("Apple Inc.")).toBeNull();
  });

  it("returns focus to whatever had it when the palette opened, once it closes", () => {
    render(
      <div>
        <button>Trigger</button>
        <CommandPalette />
      </div>,
    );
    const trigger = screen.getByRole("button", { name: "Trigger" });
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.activeElement).toBe(trigger);
  });
});

describe("CommandPalette — controlled open (visible search bar trigger)", () => {
  it("renders open when the open prop is true, with no shortcut needed", () => {
    render(<CommandPalette open onOpenChange={() => {}} />);
    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
  });

  it("stays closed when the open prop is false", () => {
    render(<CommandPalette open={false} onOpenChange={() => {}} />);
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
  });

  it("calls onOpenChange(false) on Escape rather than managing its own state", () => {
    const onOpenChange = vi.fn();
    render(<CommandPalette open onOpenChange={onOpenChange} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});