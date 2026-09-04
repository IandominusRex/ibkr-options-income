import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NewsPanel } from "./NewsPanel";

const items = [
  {
    title: "Apple surges on strong earnings",
    url: "https://example.com/1",
    published_at: new Date(Date.now() - 30 * 60000).toISOString(),
    source: "Reuters",
    sentiment: 0.6,
  },
  {
    title: "Apple faces antitrust probe",
    url: "https://example.com/2",
    published_at: new Date(Date.now() - 2 * 3600000).toISOString(),
    source: "Bloomberg",
    sentiment: -0.4,
  },
  {
    title: "Apple announces dividend",
    url: null,
    published_at: null,
    source: null,
    sentiment: 0.0,
  },
];

describe("NewsPanel", () => {
  it("lists headlines newest first with a relative age", () => {
    render(<NewsPanel items={items} />);
    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveAttribute("href", "https://example.com/1");
    expect(screen.getByText("30m ago")).toBeInTheDocument();
    expect(screen.getByText("2h ago")).toBeInTheDocument();
  });

  it("links out with rel=noopener noreferrer", () => {
    render(<NewsPanel items={items} />);
    const link = screen.getAllByRole("link")[0];
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("shows per-item sentiment as a labelled chip, not colour-only", () => {
    render(<NewsPanel items={items} />);
    expect(screen.getByText("bullish")).toBeInTheDocument();
    expect(screen.getByText("bearish")).toBeInTheDocument();
    expect(screen.getByText("neutral")).toBeInTheDocument();
  });

  it("renders a no-link title as plain text, not an anchor", () => {
    render(<NewsPanel items={items} />);
    expect(screen.getByText("Apple announces dividend")).toBeInTheDocument();
    expect(screen.getAllByRole("link").length).toBe(2);
  });

  it("shows a message when there are no headlines", () => {
    render(<NewsPanel items={[]} />);
    expect(screen.getByText("No recent headlines.")).toBeInTheDocument();
  });
});