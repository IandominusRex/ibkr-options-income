import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TickerPillBar } from "./TickerPillBar";
import type { ApprovalSummary } from "./types";

function approval(overrides: Partial<ApprovalSummary>): ApprovalSummary {
  return {
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
    created_at: "2026-09-01T00:00:00Z",
    expires_at: null,
    decided_at: null,
    order_state: null,
    source: "scan",
    ...overrides,
  };
}

describe("TickerPillBar", () => {
  it("renders one pill per unique ticker present in the approvals list", () => {
    render(
      <TickerPillBar
        approvals={[
          approval({ id: 1, underlying: "NVDA" }),
          approval({ id: 2, underlying: "NVDA" }),
          approval({ id: 3, underlying: "AAPL" }),
        ]}
        selected={null}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /NVDA/ })).toBeDefined();
    expect(screen.getByRole("button", { name: /AAPL/ })).toBeDefined();
    // One pill per ticker, not one per approval.
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("shows each ticker's count of options in the list", () => {
    render(
      <TickerPillBar
        approvals={[
          approval({ id: 1, underlying: "NVDA" }),
          approval({ id: 2, underlying: "NVDA" }),
        ]}
        selected={null}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /NVDA/ }).textContent).toContain("2");
  });

  it("renders nothing when there are no approvals", () => {
    const { container } = render(
      <TickerPillBar approvals={[]} selected={null} onSelect={() => {}} />,
    );
    expect(container.textContent).toBe("");
  });

  it("calls onSelect with the ticker when its pill is clicked", () => {
    const onSelect = vi.fn();
    render(
      <TickerPillBar
        approvals={[approval({ id: 1, underlying: "NVDA" })]}
        selected={null}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /NVDA/ }));
    expect(onSelect).toHaveBeenCalledWith("NVDA");
  });

  it("calls onSelect(null) when the already-selected pill is clicked again", () => {
    const onSelect = vi.fn();
    render(
      <TickerPillBar
        approvals={[approval({ id: 1, underlying: "NVDA" })]}
        selected="NVDA"
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /NVDA/ }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("marks the selected pill with aria-pressed", () => {
    render(
      <TickerPillBar
        approvals={[
          approval({ id: 1, underlying: "NVDA" }),
          approval({ id: 2, underlying: "AAPL" }),
        ]}
        selected="NVDA"
        onSelect={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /NVDA/ }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByRole("button", { name: /AAPL/ }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });
});
