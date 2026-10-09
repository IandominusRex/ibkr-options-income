import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NewsCard } from "./NewsCard";
import type { NewsPost } from "./types";

const POST: NewsPost = {
  id: 1, kind: "macro_print", subject: null, posted_at: "2026-10-14T12:31:00Z", stage: "explained",
  critical: true, silent: false, has_chart: false,
  payload: {
    kind: "macro_print", title: "CPI hotter than expected", emoji: "🔴", when: "2026-10-14T12:30:00Z",
    headline_line: "CPI m/m 0.4% vs 0.3% est",
    grid: [{ asset: "stocks", textbook: "🔴", actual: "🔴 ES=F -1.20%" }],
    explanation: { headline: "h", what_happened: "w", read: "Inflation re-accelerating.", bull: "core cooling", bear: "shelter sticky",
      verdict: "further_downside_likely", confidence: "medium", book_impact: "NVDA 165P 3.1% OTM", setup_impact: "", evidence: ["F1"] },
    links: [{ name: "BLS", url: "https://www.bls.gov/x" }], updates: [], sections: [],
  },
};

describe("NewsCard", () => {
  it("renders the grid, verdict as text plus icon, book line and inline links", () => {
    render(<NewsCard post={POST} />);
    expect(screen.getByText("CPI hotter than expected")).toBeInTheDocument();
    expect(screen.getByTestId("grid-stocks")).toHaveTextContent("ES=F -1.20%");
    expect(screen.getByTestId("verdict")).toHaveTextContent("Further downside likely");
    expect(screen.getByText(/NVDA 165P 3.1% OTM/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BLS" })).toHaveAttribute("href", "https://www.bls.gov/x");
  });

  it("never renders an em dash in UI copy", () => {
    const { container } = render(<NewsCard post={POST} />);
    expect(container.textContent).not.toContain("—");
  });
});
