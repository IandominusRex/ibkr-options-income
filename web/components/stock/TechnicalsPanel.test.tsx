import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TechnicalsPanel } from "./TechnicalsPanel";

const full = {
  price: 221.4,
  rsi_14: 55.2,
  atr_14: 3.1,
  macd: 0.5,
  macd_signal: 0.3,
  sma_20: 218.0,
  sma_50: 210.0,
  sma_200: 195.0,
  phase: "Stage 2",
  regime: "bull",
};

describe("TechnicalsPanel", () => {
  it("shows every metric and the phase/regime badges", () => {
    render(<TechnicalsPanel data={full} />);
    expect(screen.getByText("RSI 14")).toBeInTheDocument();
    expect(screen.getByText("55.20")).toBeInTheDocument();
    expect(screen.getByText("MACD")).toBeInTheDocument();
    expect(screen.getByText("SMA 50")).toBeInTheDocument();
    expect(screen.getByText("SMA 200")).toBeInTheDocument();
    expect(screen.getByText("ATR 14")).toBeInTheDocument();
    expect(screen.getByText(/Stage 2/)).toBeInTheDocument();
    expect(screen.getByText(/bull/)).toBeInTheDocument();
  });

  it("renders n/a for null metrics, never 0", () => {
    const sparse = {
      ...full,
      rsi_14: null,
      macd: null,
      phase: null,
      regime: null,
    };
    render(<TechnicalsPanel data={sparse} />);
    expect(screen.getAllByText("n/a").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Phase: n\/a/)).toBeInTheDocument();
    expect(screen.getByText(/Regime: n\/a/)).toBeInTheDocument();
  });
});