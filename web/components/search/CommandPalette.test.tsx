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
});