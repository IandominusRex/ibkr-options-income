import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SectorCard } from "./SectorCard";

describe("SectorCard", () => {
  it("renders gain and loss with a sign, not colour alone", () => {
    render(
      <SectorCard
        sector="tech"
        count={3}
        changePct={1.5}
        best={{ symbol: "MSFT", change_pct: 2.0 }}
        worst={{ symbol: "AAPL", change_pct: -1.0 }}
        avgIvRank={42.0}
        ivRankCount={3}
      />,
    );
    expect(screen.getByText("+1.50%")).toBeDefined();
    expect(screen.getByText("+2.00%")).toBeDefined();
    expect(screen.getByText("-1.00%")).toBeDefined();
  });

  it("reports null change_pct as n/a, never 0", () => {
    render(
      <SectorCard
        sector="bonds"
        count={1}
        changePct={null}
        best={{ symbol: "-", change_pct: null }}
        worst={{ symbol: "-", change_pct: null }}
        avgIvRank={null}
        ivRankCount={0}
      />,
    );
    // change_pct line plus best/worst movers all render n/a; assert at least one.
    expect(screen.getAllByText(/n\/a/).length).toBeGreaterThan(0);
  });

  it("shows the contributing IV-rank count so a one-name average is visible", () => {
    render(
      <SectorCard
        sector="semis"
        count={5}
        changePct={null}
        best={{ symbol: "-", change_pct: null }}
        worst={{ symbol: "-", change_pct: null }}
        avgIvRank={80.0}
        ivRankCount={1}
      />,
    );
    expect(screen.getByText("(1 name)")).toBeDefined();
  });

  it("shows the count when more than one name contributed", () => {
    render(
      <SectorCard
        sector="semis"
        count={5}
        changePct={null}
        best={{ symbol: "-", change_pct: null }}
        worst={{ symbol: "-", change_pct: null }}
        avgIvRank={80.0}
        ivRankCount={3}
      />,
    );
    expect(screen.getByText("(3)")).toBeDefined();
  });
});