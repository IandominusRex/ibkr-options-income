import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/lib/test-query";

vi.mock("next/navigation", () => ({ usePathname: () => "/trades/41" }));

import { OPEN_SEARCH_EVENT } from "@/lib/search";
import { Rail } from "./Rail";

const controls = {
  as_of: new Date().toISOString(),
  autonomy: { level: "approve", label: "Approve each trade" },
  rungs: [],
  halted: false,
  halt_reason: null,
  halted_at: null,
  mode: "paper",
  drain_healthy: true,
  drain_last_seen: null,
  pending_commands: 0,
};

function approvals(n: number) {
  return {
    as_of: new Date().toISOString(),
    approvals: Array.from({ length: n }, (_, i) => ({ id: i + 1, status: "pending" })),
  };
}

describe("Rail", () => {
  it("lists every destination and marks the current one", () => {
    renderWithQuery(<Rail />, { "/options/controls": controls, "/options/approvals": approvals(0) });
    for (const name of ["Home", "Portfolio", "Activity", "Research", "News", "More"]) {
      expect(screen.getByRole("link", { name: new RegExp(`^${name}`) })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: /^Trades/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /^Home/ })).not.toHaveAttribute("aria-current");
  });
  it("shows the pending count on Trades in words for screen readers", async () => {
    renderWithQuery(<Rail />, { "/options/controls": controls, "/options/approvals": approvals(2) });
    expect(await screen.findByText("2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Trades, 2 waiting" })).toBeInTheDocument();
  });
  it("shows no badge when nothing is waiting", async () => {
    renderWithQuery(<Rail />, { "/options/controls": controls, "/options/approvals": approvals(0) });
    expect(await screen.findByRole("link", { name: "Trades" })).toBeInTheDocument();
  });
  it("offers Search under the wordmark, which opens the console's one palette", async () => {
    renderWithQuery(<Rail />, { "/options/controls": controls, "/options/approvals": approvals(0) });
    const seen = vi.fn();
    window.addEventListener(OPEN_SEARCH_EVENT, seen);
    const button = screen.getByRole("button", { name: "Search" });
    expect(button).toHaveAttribute("aria-keyshortcuts", "Meta+K Control+K");
    fireEvent.click(button);
    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
