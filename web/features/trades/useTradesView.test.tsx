import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/trades",
}));

import { detailHref, tradesReturnQuery, useTradesDay, useTradesView } from "./useTradesView";

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
});

describe("useTradesView", () => {
  it("reads ?view=", () => {
    nav.params = new URLSearchParams("view=assessed");
    const { result } = renderHook(() => useTradesView("all", 3));
    expect(result.current[0]).toBe("assessed");
  });
  it("opens History for a retired view name", () => {
    nav.params = new URLSearchParams("view=decided");
    const { result } = renderHook(() => useTradesView("all", 3));
    expect(result.current[0]).toBe("history");
  });
  it("opens Proposals when something waits on you, History when nothing does, nothing while unknown", () => {
    expect(renderHook(() => useTradesView("all", 2)).result.current[0]).toBe("proposals");
    expect(renderHook(() => useTradesView("all", 0)).result.current[0]).toBe("history");
    expect(renderHook(() => useTradesView("all", null)).result.current[0]).toBeNull();
  });
  it("opens History when the pending count could not be loaded, and keeps it if the load later recovers", () => {
    const { result, rerender } = renderHook(
      ({ n, failed }: { n: number | null; failed: boolean }) => useTradesView("all", n, failed),
      { initialProps: { n: null as number | null, failed: true } },
    );
    expect(result.current[0]).toBe("history");
    rerender({ n: 2, failed: false });
    expect(result.current[0]).toBe("history");
  });
  it("still waits while the pending count is loading and has not failed", () => {
    const { result } = renderHook(() => useTradesView("all", null, false));
    expect(result.current[0]).toBeNull();
  });
  it("lets a count that arrives before the failure decide, not the failure", () => {
    const { result } = renderHook(() => useTradesView("all", 2, true));
    expect(result.current[0]).toBe("proposals");
  });
  it("keeps the default it chose when the last proposal is approved", () => {
    const { result, rerender } = renderHook(({ n }: { n: number | null }) => useTradesView("all", n), {
      initialProps: { n: 1 },
    });
    expect(result.current[0]).toBe("proposals");
    rerender({ n: 0 });
    expect(result.current[0]).toBe("proposals");
  });
  it("writes a view into the URL and keeps the strategy", () => {
    nav.params = new URLSearchParams("strategy=csp");
    const { result } = renderHook(() => useTradesView("csp", 0));
    act(() => result.current[1]("history"));
    expect(nav.replace).toHaveBeenCalledWith("/trades?strategy=csp&view=history", { scroll: false });
  });
  it("shows Spreads for credit spreads whatever the URL says", () => {
    nav.params = new URLSearchParams("strategy=spread&view=history");
    const { result } = renderHook(() => useTradesView("spread", null));
    expect(result.current[0]).toBe("spreads");
  });
});

describe("useTradesDay", () => {
  it("reads a well-formed ?day= and ignores anything else", () => {
    nav.params = new URLSearchParams("day=2026-10-09");
    expect(renderHook(() => useTradesDay()).result.current[0]).toBe("2026-10-09");
    nav.params = new URLSearchParams("day=yesterday");
    expect(renderHook(() => useTradesDay()).result.current[0]).toBeNull();
  });
  it("accepts only a real calendar date: a well-shaped impossible one falls back to today", () => {
    for (const bad of ["2026-13-45", "2026-02-30", "2026-00-10", "2026-10-00", "2025-02-29"]) {
      nav.params = new URLSearchParams(`day=${bad}`);
      expect(renderHook(() => useTradesDay()).result.current[0], bad).toBeNull();
    }
    nav.params = new URLSearchParams("day=2028-02-29");
    expect(renderHook(() => useTradesDay()).result.current[0]).toBe("2028-02-29");
  });
  it("writes and clears the day, keeping the rest of the URL", () => {
    nav.params = new URLSearchParams("view=history");
    const { result } = renderHook(() => useTradesDay());
    act(() => result.current[1]("2026-10-09"));
    expect(nav.replace).toHaveBeenLastCalledWith("/trades?view=history&day=2026-10-09", { scroll: false });
    nav.params = new URLSearchParams("view=history&day=2026-10-09");
    const again = renderHook(() => useTradesDay());
    act(() => again.result.current[1](null));
    expect(nav.replace).toHaveBeenLastCalledWith("/trades?view=history", { scroll: false });
  });
});

describe("tradesReturnQuery", () => {
  it("keeps only view, day and strategy, in that order, and drops the rest", () => {
    const p = new URLSearchParams("x=1&strategy=csp&symbol=AAPL&day=2026-11-03&view=history");
    expect(tradesReturnQuery(p)).toBe("view=history&day=2026-11-03&strategy=csp");
  });
  it("validates each: an unknown view, an impossible day and an unknown strategy are dropped", () => {
    expect(tradesReturnQuery(new URLSearchParams("view=nope&day=2026-02-30&strategy=value"))).toBe("");
    expect(tradesReturnQuery(new URLSearchParams("view=assessed&day=junk&strategy=zzz"))).toBe("view=assessed");
  });
  it("is empty for nothing, and for no params at all", () => {
    expect(tradesReturnQuery(new URLSearchParams())).toBe("");
    expect(tradesReturnQuery(null)).toBe("");
  });
});

describe("detailHref", () => {
  it("is the detail page, with the return query when there is one", () => {
    expect(detailHref(42, "")).toBe("/trades/42");
    expect(detailHref(42, "view=history&day=2026-11-03")).toBe("/trades/42?view=history&day=2026-11-03");
  });
});
