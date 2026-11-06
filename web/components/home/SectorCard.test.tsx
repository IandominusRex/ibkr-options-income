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
describe("SectorCard, restyled (web overhaul Part 6)", () => {
  it("never colours a move green or red: a sector's move is a price, not money", () => {
    const { container } = render(
      <ul>
        <SectorCard
          sector="tech"
          count={3}
          changePct={-1.5}
          best={{ symbol: "MSFT", change_pct: 2.0 }}
          worst={{ symbol: "AAPL", change_pct: -1.0 }}
          avgIvRank={42.0}
          ivRankCount={3}
        />
      </ul>,
    );
    expect(container.querySelector(".text-gain, .text-loss")).toBeNull();
    expect(screen.getByRole("heading", { level: 3, name: "tech" })).toBeDefined();
    expect(container.textContent).toContain("3 names · -1.50% today");
    expect(container.textContent).toContain("Best MSFT +2.00% · worst AAPL -1.00%");
  });

  it("hatches every unknown, so n/a never reads as zero", () => {
    const { container } = render(
      <ul>
        <SectorCard
          sector="bonds"
          count={1}
          changePct={null}
          best={{ symbol: "TLT", change_pct: null }}
          worst={{ symbol: "TLT", change_pct: null }}
          avgIvRank={null}
          ivRankCount={0}
        />
      </ul>,
    );
    expect(container.querySelectorAll(".hatch").length).toBe(4);
    expect(container.textContent).toContain("1 name");
  });
});
