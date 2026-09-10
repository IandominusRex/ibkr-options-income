import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FreshnessLabel } from "./FreshnessLabel";

describe("FreshnessLabel", () => {
  it("states the age in words", () => {
    const when = new Date(Date.now() - 12 * 60 * 1000).toISOString();
    render(<FreshnessLabel asOf={when} freshForMinutes={30} />);
    expect(screen.getByText(/12m ago/)).toBeInTheDocument();
  });

  it("says stale in words when it is stale", () => {
    const when = new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString();
    render(<FreshnessLabel asOf={when} freshForMinutes={30} />);
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
  });

  it("does not say stale for a fresh reading", () => {
    const when = new Date(Date.now() - 12 * 60 * 1000).toISOString();
    render(<FreshnessLabel asOf={when} freshForMinutes={30} />);
    expect(screen.queryByText(/stale/i)).toBeNull();
  });

  it("renders nothing-captured distinctly from just-now", () => {
    render(<FreshnessLabel asOf={null} freshForMinutes={30} />);
    expect(screen.getByText(/not captured/i)).toBeInTheDocument();
    expect(screen.queryByText(/just now/i)).toBeNull();
  });

  it("does not render stale wording for a null reading", () => {
    render(<FreshnessLabel asOf={null} freshForMinutes={30} />);
    expect(screen.queryByText(/stale/i)).toBeNull();
  });
});
