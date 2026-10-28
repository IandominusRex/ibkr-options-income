import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useLegFilters } from "./useLegFilters";

describe("useLegFilters", () => {
  it("starts on both books with one query string", () => {
    const { result } = renderHook(() => useLegFilters());
    expect(result.current.book).toBe("all");
    expect(result.current.qsString).toBe("book=all");
  });
  it("puts the book into the same filters the other fields use", () => {
    const { result } = renderHook(() => useLegFilters());
    act(() => result.current.setBook("paper"));
    expect(result.current.book).toBe("paper");
    expect(result.current.qsString).toBe("book=paper");
  });
  it("drops empty filters from the query string and keeps the book", () => {
    const { result } = renderHook(() => useLegFilters());
    act(() => result.current.setFilters({ book: "live", outcome: "", since: "2026-09-01", until: "", symbol: "NVDA" }));
    expect(result.current.qsString).toBe("book=live&since=2026-09-01&symbol=NVDA");
  });
  it("adds the book when the filters name none", () => {
    const { result } = renderHook(() => useLegFilters());
    act(() => result.current.setFilters({ symbol: "AMD" }));
    expect(result.current.qsString).toBe("symbol=AMD&book=all");
  });
  it("sets the symbol from a leg and remounts the filter form once", () => {
    const { result } = renderHook(() => useLegFilters());
    const before = result.current.formKey;
    act(() => result.current.viewLeg({ underlying: "NVDA" } as never));
    expect(result.current.filters.symbol).toBe("NVDA");
    expect(result.current.qsString).toBe("symbol=NVDA&book=all");
    expect(result.current.formKey).toBe(before + 1);
  });
});
