import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { PositionRowItem } from "./PositionRowItem";
import type { PositionRow } from "./positions";

const row = (over: Partial<PositionRow> = {}): PositionRow => ({
  key: "AAPL:x",
  kind: "csp",
  underlying: "AAPL",
  href: "/positions/AAPL/2099-11-21_P180",
  title: "AAPL $180 put",
  status: { word: "Out of the money", tone: "neutral" },
  alert: false,
  sub: "Sat, 21 Nov · 30d",
  value: 38,
  valueLabel: "open P&L",
  sortKey: "2099-11-21",
  ...over,
});
const ctx = { "/claude/context": { available: true, dossiers: [{ symbol: "AAPL", health: "weak", events: [] }] } };
const inList = (ui: React.ReactElement) => <ul>{ui}</ul>;

describe("PositionRowItem", () => {
  it("draws the title, the status word, the sub-line and the signed value, and links to the contract", () => {
    renderWithQuery(inList(<PositionRowItem row={row()} />), ctx);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/positions/AAPL/2099-11-21_P180");
    expect(screen.getByText("AAPL $180 put")).toBeInTheDocument();
    expect(screen.getByText("Out of the money")).toBeInTheDocument();
    expect(screen.getByText("+$38.00")).toBeInTheDocument();
  });
  it("is not a link when the contract is not fully known", () => {
    renderWithQuery(inList(<PositionRowItem row={row({ href: null })} />), ctx);
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("shows the name's flags unless asked not to", async () => {
    renderWithQuery(inList(<PositionRowItem row={row()} />), ctx);
    expect(await screen.findByText("Weak health")).toBeInTheDocument();
  });
  it("leaves the flags to the card header when flags is false, and shows a detail line", () => {
    const before = apiFetchMock.mock.calls.length;
    renderWithQuery(inList(<PositionRowItem row={row()} flags={false} detail="delta -0.21" />), ctx);
    expect(screen.getByText("delta -0.21")).toBeInTheDocument();
    // NameFlags is not mounted, so the row never asks for the name's notes.
    expect(apiFetchMock.mock.calls.length).toBe(before);
  });
  it("draws an unknown value as a hatched n/a, never $0", () => {
    renderWithQuery(inList(<PositionRowItem row={row({ value: null })} />), ctx);
    expect(screen.getByText("n/a")).toHaveClass("hatch");
  });
});
