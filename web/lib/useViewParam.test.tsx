import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/portfolio",
}));

import { useViewParam } from "./useViewParam";

const VIEWS = ["positions", "campaigns", "calendar"] as const;

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
});

describe("useViewParam", () => {
  it("reads ?view=", () => {
    nav.params = new URLSearchParams("view=calendar");
    const { result } = renderHook(() => useViewParam(VIEWS, "positions"));
    expect(result.current[0]).toBe("calendar");
  });
  it("falls back when there is no view or the view is not one of the page's", () => {
    expect(renderHook(() => useViewParam(VIEWS, "positions")).result.current[0]).toBe("positions");
    nav.params = new URLSearchParams("view=foo");
    expect(renderHook(() => useViewParam(VIEWS, "positions")).result.current[0]).toBe("positions");
    nav.params = new URLSearchParams("view=");
    expect(renderHook(() => useViewParam(VIEWS, "positions")).result.current[0]).toBe("positions");
  });
  it("writes the view into the URL and keeps the other parameters", () => {
    nav.params = new URLSearchParams("month=2026-09");
    const { result } = renderHook(() => useViewParam(VIEWS, "positions"));
    act(() => result.current[1]("calendar"));
    expect(nav.replace).toHaveBeenCalledWith("/portfolio?month=2026-09&view=calendar", { scroll: false });
  });
  it("replaces a view that is already there", () => {
    nav.params = new URLSearchParams("view=positions&x=1");
    const { result } = renderHook(() => useViewParam(VIEWS, "positions"));
    act(() => result.current[1]("campaigns"));
    expect(nav.replace).toHaveBeenCalledWith("/portfolio?view=campaigns&x=1", { scroll: false });
  });
});
