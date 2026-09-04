import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatementsTable } from "./StatementsTable";

const financials = {
  symbol: "AAPL",
  cik: "0000320193",
  entity_name: "Apple Inc.",
  annual: [
    {
      period_end: "2024-09-28",
      period_type: "annual",
      items: {
        revenue: {
          line_item: "revenue",
          value: 391035000000,
          concept: "Revenues",
          accn: "0000320193-24-000123",
          filed: "2024-11-01",
          form: "10-K",
        },
      },
    },
  ],
  quarterly: [
    {
      period_end: "2024-06-29",
      period_type: "quarterly",
      items: {
        revenue: {
          line_item: "revenue",
          value: 85777000000,
          concept: "Revenues",
          accn: "0000320193-24-000123",
          filed: "2024-08-01",
          form: "10-Q",
        },
      },
    },
  ],
};

describe("StatementsTable", () => {
  it("renders the annual period column header", () => {
    render(<StatementsTable financials={financials} />);
    expect(screen.getByText("Sep 2024")).toBeDefined();
  });

  it("renders the quarterly section when quarterly data is present", () => {
    render(<StatementsTable financials={financials} />);
    expect(screen.getByText("Quarterly")).toBeDefined();
    expect(screen.getByText("Jun 2024")).toBeDefined();
  });

  it("formats the annual value", () => {
    render(<StatementsTable financials={financials} />);
    expect(screen.getByText("$391.0B")).toBeDefined();
  });

  it("formats the quarterly value", () => {
    render(<StatementsTable financials={financials} />);
    expect(screen.getByText("$85.8B")).toBeDefined();
  });

  it("exposes filing traceability on the cell", () => {
    render(<StatementsTable financials={financials} />);
    const cell = screen.getByText("$391.0B");
    expect(cell.getAttribute("title")).toContain("0000320193-24-000123");
    expect(cell.getAttribute("title")).toContain("Revenues");
  });

  it("renders a missing line item as n/a rather than zero", () => {
    render(<StatementsTable financials={financials} />);
    expect(screen.getAllByText("n/a").length).toBeGreaterThan(0);
  });

  it("applies the hatch texture class to unknown cells, not colour alone", () => {
    const { container } = render(<StatementsTable financials={financials} />);
    // Unknown cells carry the .hatch texture per web/CLAUDE.md: state is never
    // encoded by colour alone.
    const hatchCells = container.querySelectorAll(".hatch");
    expect(hatchCells.length).toBeGreaterThan(0);
    // Every hatch cell renders the UNKNOWN marker, so texture and text agree.
    hatchCells.forEach((node) => {
      expect(node.textContent).toBe("n/a");
    });
  });

  it("does not use an em dash in the title attribute", () => {
    render(<StatementsTable financials={financials} />);
    const cell = screen.getByText("$391.0B");
    const title = cell.getAttribute("title") ?? "";
    expect(title).not.toContain("\u2014");
  });
});