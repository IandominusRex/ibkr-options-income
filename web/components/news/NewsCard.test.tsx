import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
    expect(screen.getByRole("link", { name: "BLS (opens in a new tab)" })).toHaveAttribute("href", "https://www.bls.gov/x");
  });

  it("renders two identical update lines without a duplicate-key warning", () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const same = "🔄 Update: SPY -2.0%";
    render(<NewsCard post={{ ...POST, payload: { ...POST.payload, updates: [same, same] } }} />);
    expect(screen.getAllByText(same)).toHaveLength(2);
    expect(err.mock.calls.some((c) => String(c[0]).includes("same key"))).toBe(false);
    err.mockRestore();
  });

  it("labels the explanation as the news model's reading, never as Claude's alone", () => {
    render(<NewsCard post={POST} />);
    const reading = screen.getByTestId("news-reading");
    expect(reading).toHaveTextContent("The news model's reading");
    expect(reading).toHaveTextContent("Claude, or the local model when Claude cannot be reached; it trades nothing");
    expect(reading).toHaveTextContent("Inflation re-accelerating.");
  });

  it("draws the verdict in ink with its icon and words: a forecast is not money, so never green or red", () => {
    for (const verdict of ["further_downside_likely", "further_upside_likely"] as const) {
      const { unmount } = render(
        <NewsCard post={{ ...POST, payload: { ...POST.payload, explanation: { ...POST.payload.explanation!, verdict } } }} />,
      );
      const pill = screen.getByTestId("verdict");
      expect(pill).toHaveClass("text-content");
      expect(pill.className).not.toMatch(/text-(gain|loss)/);
      expect(pill).toHaveTextContent(verdict === "further_upside_likely" ? "▲" : "▼");
      expect(pill).toHaveTextContent("medium confidence");
      unmount();
    }
  });

  it("says Critical as a flag word, and names a source link as opening a new tab", () => {
    render(<NewsCard post={POST} />);
    expect(screen.getByText("Critical")).toHaveAttribute("data-tone", "flag");
    expect(screen.getByRole("link", { name: "BLS (opens in a new tab)" })).toHaveAttribute("target", "_blank");
  });

  it("says once that a digest's readings are the news model's", () => {
    const sections = [{ title: "Movers", items: [{ text: "NVDA -4%", read: "Profit taking.", verdict: "priced_in" as const, links: [] }] }];
    render(<NewsCard post={{ ...POST, payload: { ...POST.payload, explanation: null, sections } }} />);
    expect(screen.getByText("The readings and verdicts below are the news model's.")).toBeInTheDocument();
  });

  it("never renders an em dash in UI copy", () => {
    const { container } = render(<NewsCard post={POST} />);
    expect(container.textContent).not.toContain("—");
  });
});
