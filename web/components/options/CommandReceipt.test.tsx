import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CommandReceipt } from "./CommandReceipt";
import type { CommandStatus } from "@/lib/commands";
import type { OrderSummary } from "./types";

function command(overrides: Partial<CommandStatus> = {}): CommandStatus {
  return {
    id: 41,
    kind: "approve",
    status: "pending",
    result: null,
    needs_confirmation: false,
    confirm_token: null,
    created_at: "2026-09-06T12:00:00Z",
    applied_at: null,
    as_of: "2026-09-06T12:00:00Z",
    ...overrides,
  };
}

function order(overrides: Partial<OrderSummary> = {}): OrderSummary | null {
  return {
    as_of: "2026-09-06T12:00:00Z",
    id: 7,
    candidate_id: "c1",
    approval_id: 41,
    underlying: "NVDA",
    strategy: "cash_secured_put",
    strike: 190,
    expiry: "2026-10-16",
    state: "submitted",
    limit_price: 2.45,
    filled_qty: 0,
    avg_fill_price: null,
    is_live: false,
    detail: null,
    created_at: "2026-09-06T12:00:00Z",
    updated_at: "2026-09-06T12:00:00Z",
    ...overrides,
  };
}

describe("CommandReceipt", () => {
  it("renders the intent id on every receipt", () => {
    render(<CommandReceipt command={command()} order={null} drainHealthy={true} />);
    expect(screen.getByText(/intent 41/)).toBeDefined();
  });

  it("renders queued distinctly from applied — label and data-state differ", () => {
    const { rerender } = render(
      <CommandReceipt command={command()} order={null} drainHealthy={true} />,
    );
    const queued = screen.getByTestId("command-receipt");
    expect(queued.getAttribute("data-state")).toBe("queued");
    expect(screen.getByText("Queued")).toBeDefined();

    rerender(
      <CommandReceipt command={command({ status: "applied" })} order={null} drainHealthy={true} />,
    );
    const applied = screen.getByTestId("command-receipt");
    expect(applied.getAttribute("data-state")).toBe("applied");
    expect(screen.getByText("Applied")).toBeDefined();
  });

  it("states the stalled drain in words and renders no spinner", () => {
    render(<CommandReceipt command={command()} order={null} drainHealthy={false} />);
    // The words appear as the receipt's copy — a stalled drain is stated,
    // not spun (spec §9.2 rule 3).
    expect(
      screen.getAllByText("the trading service is not draining commands").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("renders submitted only when an order is working at the broker", () => {
    const { rerender } = render(
      <CommandReceipt
        command={command({ status: "applied" })}
        order={null}
        drainHealthy={true}
      />,
    );
    expect(screen.getByTestId("command-receipt").getAttribute("data-state")).toBe("applied");

    rerender(
      <CommandReceipt
        command={command({ status: "applied" })}
        order={order({ state: "submitted" })}
        drainHealthy={true}
      />,
    );
    expect(screen.getByTestId("command-receipt").getAttribute("data-state")).toBe("submitted");
  });

  it("renders filled with the fill details when a fill exists", () => {
    render(
      <CommandReceipt
        command={command({ status: "applied" })}
        order={order({ state: "filled", filled_qty: 2, avg_fill_price: 2.47 })}
        drainHealthy={true}
      />,
    );
    expect(screen.getByTestId("command-receipt").getAttribute("data-state")).toBe("filled");
    expect(screen.getByText("Filled")).toBeDefined();
  });

  it("renders the humanised failure reason plus detail reason codes", () => {
    render(
      <CommandReceipt
        command={command({
          status: "failed",
          result: {
            reason: "approval_not_found",
            detail: { reasons: ["no_longer_pending"] },
          },
        })}
        order={null}
        drainHealthy={true}
      />,
    );
    expect(screen.getByText(/approval not found/)).toBeDefined();
    expect(screen.getByText(/no longer pending/)).toBeDefined();
  });

  it("renders set_autonomy's promotion_refused blockers, a different detail key than reasons", () => {
    // Regression: command_drain.py::_set_autonomy raises CommandFailed with
    // {"blockers": [...]}, not {"reasons": [...]} like promote's gate_rejected —
    // failedReason() only checked `detail.reasons`/`detail.reason`, so every
    // blocker silently vanished and a refused promotion rendered "Promotion
    // refused" with no explanation of what to fix.
    render(
      <CommandReceipt
        command={command({
          status: "failed",
          result: {
            reason: "promotion_refused",
            detail: {
              blockers: ["needs >=20 fills, has 3", "fill rate 40% is below the 60% gate"],
            },
          },
        })}
        order={null}
        drainHealthy={true}
      />,
    );
    expect(screen.getByText(/promotion refused/)).toBeDefined();
    expect(screen.getByText(/needs >=20 fills, has 3/)).toBeDefined();
    expect(screen.getByText(/fill rate 40% is below the 60% gate/)).toBeDefined();
  });

  it("renders a plainReasons failure as a plain answer, not red failed chrome (M3 3.5)", () => {
    render(
      <CommandReceipt
        command={command({
          status: "failed",
          result: { reason: "broker_unavailable" },
        })}
        order={null}
        drainHealthy={true}
        plainReasons={["broker_unavailable"]}
      />,
    );
    const receipt = screen.getByTestId("command-receipt");
    // Not the red failed state - a distinct, neutral data-state.
    expect(receipt.getAttribute("data-state")).not.toBe("failed");
    expect(screen.queryByText("Failed")).toBeNull();
    // No text-loss class anywhere in the receipt for a plain reason.
    expect(receipt.innerHTML).not.toContain("text-loss");
  });

  it("a reason not listed in plainReasons still renders the normal red failed state", () => {
    render(
      <CommandReceipt
        command={command({
          status: "failed",
          result: { reason: "broker_unavailable" },
        })}
        order={null}
        drainHealthy={true}
        plainReasons={["some_other_reason"]}
      />,
    );
    const receipt = screen.getByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("failed");
    expect(screen.getByText("Failed")).toBeDefined();
  });

  it("plainReasons defaults to empty - every existing call site stays byte-identical", () => {
    render(
      <CommandReceipt
        command={command({ status: "failed", result: { reason: "broker_unavailable" } })}
        order={null}
        drainHealthy={true}
      />,
    );
    const receipt = screen.getByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("failed");
    expect(screen.getByText("Failed")).toBeDefined();
  });
});