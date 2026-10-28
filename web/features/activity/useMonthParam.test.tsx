import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/activity",
}));

import { useMonthParam } from "./useMonthParam";

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
});

describe("useMonthParam", () => {
  it("reads ?month=, and is this month for none, junk or a future month", () => {
    nav.params = new URLSearchParams("month=2026-09");
    expect(renderHook(() => useMonthParam("2026-10")).result.current[0]).toBe("2026-09");
    nav.params = new URLSearchParams("month=2027-01");
    expect(renderHook(() => useMonthParam("2026-10")).result.current[0]).toBe("2026-10");
    nav.params = new URLSearchParams();
    expect(renderHook(() => useMonthParam("2026-10")).result.current[0]).toBe("2026-10");
  });
  it("writes a past month and keeps the view", () => {
    nav.params = new URLSearchParams("view=pay");
    const { result } = renderHook(() => useMonthParam("2026-10"));
    act(() => result.current[1]("2026-08"));
    expect(nav.replace).toHaveBeenCalledWith("/activity?view=pay&month=2026-08", { scroll: false });
  });
  it("removes the parameter when the month chosen is this month", () => {
    nav.params = new URLSearchParams("view=pay&month=2026-08");
    const { result } = renderHook(() => useMonthParam("2026-10"));
    act(() => result.current[1]("2026-10"));
    expect(nav.replace).toHaveBeenCalledWith("/activity?view=pay", { scroll: false });
  });
  it("goes to the bare path when nothing else is left", () => {
    nav.params = new URLSearchParams("month=2026-08");
    const { result } = renderHook(() => useMonthParam("2026-10"));
    act(() => result.current[1]("2026-10"));
    expect(nav.replace).toHaveBeenCalledWith("/activity", { scroll: false });
  });
});
