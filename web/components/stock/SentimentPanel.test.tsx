import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SentimentPanel } from "./SentimentPanel";

const full = {
  overall: 62.5,
  label: "Lean bullish",
  delta_1d: 3.2,
  stocktwits: 65.0,
  stocktwits_msgs: 42,
  news: 58.0,
  news_count: 15,
  reddit: 60.0,
  top_headline: "Apple surges",
};

describe("SentimentPanel", () => {
  it("shows the composite score, label, and 1-day delta", () => {
    render(<SentimentPanel data={full} />);
    expect(screen.getByText("62.5")).toBeInTheDocument();
    expect(screen.getByText("Lean bullish")).toBeInTheDocument();
    expect(screen.getByText("+3.2 1d")).toBeInTheDocument();
  });

  it("shows the sample count for each source", () => {
    render(<SentimentPanel data={full} />);
    expect(screen.getByText("42 samples")).toBeInTheDocument();
    expect(screen.getByText("15 samples")).toBeInTheDocument();
  });

  it("renders n/a for overall when there is no data", () => {
    const empty = {
      ...full,
      overall: null,
      delta_1d: null,
      stocktwits: null,
      news: null,
      reddit: null,
    };
    render(<SentimentPanel data={empty} />);
    expect(screen.getAllByText("n/a").length).toBeGreaterThanOrEqual(1);
  });

  it("shows the 1-day delta as a loss colour when negative", () => {
    const neg = { ...full, delta_1d: -2.0 };
    render(<SentimentPanel data={neg} />);
    expect(screen.getByText("-2.0 1d")).toBeInTheDocument();
  });

  it("never fabricates a sample count for a source that doesn't track one", () => {
    // Reddit has a score but the schema carries no sample count for it — showing "0
    // samples" would misrepresent an untracked count as a real, empty one.
    render(<SentimentPanel data={full} />);
    expect(screen.getByText("n/a samples")).toBeInTheDocument();
    expect(screen.queryByText("0 samples")).not.toBeInTheDocument();
  });
});