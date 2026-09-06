import { describe, expect, it } from "vitest";
import { receiptState } from "./receipt";
import type { CommandStatus } from "./commands";
import type { OrderSummary } from "@/components/options/types";

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

function order(overrides: Partial<OrderSummary> = {}): OrderSummary {
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

describe("receiptState — the six states", () => {
  it("returns queued for a pending command with a healthy drain", () => {
    expect(receiptState(command(), null, true)).toBe("queued");
  });

  it("returns stalled for a pending command with an unhealthy drain", () => {
    expect(receiptState(command(), null, false)).toBe("stalled");
  });

  it("returns applied for an applied command with no order yet", () => {
    expect(receiptState(command({ status: "applied" }), null, true)).toBe("applied");
  });

  it("returns submitted when an order is working at the broker", () => {
    expect(
      receiptState(command({ status: "applied" }), order({ state: "submitted" }), true),
    ).toBe("submitted");
  });

  it("returns filled only when filled_qty > 0", () => {
    expect(
      receiptState(
        command({ status: "applied" }),
        order({ state: "filled", filled_qty: 2, avg_fill_price: 2.47 }),
        true,
      ),
    ).toBe("filled");
  });

  it("returns failed for a failed command", () => {
    expect(
      receiptState(command({ status: "failed", result: { reason: "approval_not_found" } }), null, true),
    ).toBe("failed");
  });
});

describe("receiptState — the three rules", () => {
  it("rule 1: pending never renders as applied, regardless of order", () => {
    // Even with a working order somehow attached, a pending command is queued.
    expect(receiptState(command({ status: "pending" }), order({ state: "submitted" }), true)).toBe(
      "queued",
    );
    // ...and stalled, in words, when the drain is dead.
    expect(receiptState(command({ status: "pending" }), order(), false)).toBe("stalled");
  });

  it("rule 2: never claim a trade happened until OrderRow says so", () => {
    // An applied command with NO order is "applied", not "submitted".
    expect(receiptState(command({ status: "applied" }), null, true)).toBe("applied");
    // A zero-filled order is not a fill.
    expect(
      receiptState(command({ status: "applied" }), order({ state: "submitted", filled_qty: 0 }), true),
    ).toBe("submitted");
    // An order row claiming `filled` with zero quantity is not a fill either —
    // the receipt refuses to claim it and falls back to `applied`.
    expect(
      receiptState(
        command({ status: "applied" }),
        order({ state: "filled", filled_qty: 0 }),
        true,
      ),
    ).toBe("applied");
    // A queued order has NOT reached the broker — the receipt stays `applied`
    // with "order queued for execution" copy, never "working at IBKR".
    expect(
      receiptState(command({ status: "applied" }), order({ state: "queued" }), true),
    ).toBe("applied");
  });

  it("rule 3: an expired command is terminal, never queued or stalled", () => {
    expect(receiptState(command({ status: "expired" }), null, false)).toBe("failed");
  });
});