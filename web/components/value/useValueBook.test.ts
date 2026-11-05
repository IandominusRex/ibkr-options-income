import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { apiFetchMock } from "@/lib/test-query";
import { useValueOut, waitingOnTap, waitingProposals } from "./useValueBook";
import type { ValueBook, ValueProposal } from "./types";

function proposal(over: Partial<ValueProposal>): ValueProposal {
  return {
    id: 1, kind: "buy", symbol: "AAPL", list_name: "deep_value", shares: 20, price: 182.4, cost_usd: 3648,
    reason: "tranche 1", cause: "python", needs_tap: true, status: "pending",
    created_at: "2026-11-05T14:00:00Z", expires_at: "2099-01-01T00:00:00Z", fingerprint: "abc123def0", ...over,
  };
}

function book(over: Partial<ValueBook>): ValueBook {
  return {
    as_of: "2026-11-05T15:00:00Z", available: true, enabled: true, ceiling_usd: 30000, used_usd: 0,
    positions: [], proposals: [], funding: [],
    breakers: { trend: false, drawdown: false, drawdown_pct: 0, trim_offered: false, trim_episode: null, trimmed: false },
    release_max_closes: 2, drain_healthy: true, drain_last_seen: "2026-11-05T14:59:30Z", ...over,
  };
}

describe("waitingOnTap", () => {
  it("counts only proposals that need a tap and are still pending", () => {
    const b = book({
      proposals: [
        proposal({ id: 1 }),
        proposal({ id: 2, status: "approved" }), // approved by a tap: no longer waiting
        proposal({ id: 3, needs_tap: false, status: "approved" }),
        proposal({ id: 4, status: "funding" }),
        proposal({ id: 5, status: "sent" }),
        proposal({ id: 6, needs_tap: false }),
      ],
    });
    expect(waitingOnTap(b)).toBe(1);
  });
  it("is null, not zero, when the book could not be read", () => {
    expect(waitingOnTap(undefined)).toBeNull();
    expect(waitingOnTap(book({ available: false }))).toBeNull();
  });
});

describe("waitingProposals", () => {
  it("lists the proposals that need a tap and are still pending, in the book's order", () => {
    const b = book({
      proposals: [
        proposal({ id: 7 }),
        proposal({ id: 2, status: "approved" }),
        proposal({ id: 3, needs_tap: false }),
        proposal({ id: 4, kind: "sell" }),
        proposal({ id: 5, status: "funding" }),
      ],
    });
    expect(waitingProposals(b)?.map((p) => p.id)).toEqual([7, 4]);
  });
  it("is an empty list when the book was read and nothing waits", () => {
    expect(waitingProposals(book({ proposals: [] }))).toEqual([]);
  });
  it("is null, not an empty list, when the book could not be read", () => {
    expect(waitingProposals(undefined)).toBeNull();
    expect(waitingProposals(book({ available: false }))).toBeNull();
  });
});

describe("useValueOut", () => {
  function run(valueAvailable: boolean | undefined, answer: () => Promise<unknown>) {
    apiFetchMock.mockImplementation(answer as never);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    return renderHook(() => useValueOut(valueAvailable), { wrapper });
  }
  const settled = () => new Promise((r) => setTimeout(r, 20));

  it("does not flag a book that is off and has never written anything", async () => {
    const { result } = run(false, async () => book({ enabled: false, available: false }));
    await waitFor(() => expect(apiFetchMock.mock.calls.length).toBeGreaterThan(0));
    await waitFor(() => expect(result.current).toBe(false));
    await settled();
    expect(result.current).toBe(false);
  });
  it("flags a book that is on but cannot be read", async () => {
    const { result } = run(false, async () => book({ enabled: true, available: false }));
    await settled();
    expect(result.current).toBe(true);
  });
  it("flags it when the book request fails (unknown is not none)", async () => {
    const { result } = run(false, async () => {
      throw new Error("down");
    });
    await settled();
    expect(result.current).toBe(true);
  });
  it("flags it while the book is still loading", () => {
    const { result } = run(false, () => new Promise(() => {}));
    expect(result.current).toBe(true);
  });
  it("never flags a P&L figure whose value book was read or whose availability is not stated", async () => {
    expect(run(true, async () => book({})).result.current).toBe(false);
    expect(run(undefined, async () => book({})).result.current).toBe(false);
  });
});
