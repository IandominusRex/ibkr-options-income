import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MonthlyBars, PnlCurve } from "./Charts";

const MONTHS = [{ month: "2026-09", premium_usd: 900, realized_usd: 700 }];
const POINTS = [{ point_date: "2026-09-01", cumulative_usd: 100 }];

describe("the ledger charts", () => {
  it("names both bars of the monthly chart in a legend, so colour is not the only key", () => {
    render(<MonthlyBars months={MONTHS} />);
    const legend = screen.getByRole("list", { name: "legend" });
    expect(within(legend).getByText("Premium")).toBeInTheDocument();
    expect(within(legend).getByText("Realised")).toBeInTheDocument();
  });

  it("keeps each chart inside its figure, under the caption, so the axis cannot run into the text below", () => {
    render(
      <>
        <PnlCurve points={POINTS} />
        <MonthlyBars months={MONTHS} />
      </>,
    );
    const figures = screen.getAllByRole("figure");
    expect(figures).toHaveLength(2);
    for (const figure of figures) expect(figure).toHaveClass("flex", "flex-col");
  });
});
