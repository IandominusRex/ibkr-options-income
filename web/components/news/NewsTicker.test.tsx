import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { NewsTicker } from "./NewsTicker";

const ISO = new Date().toISOString();

describe("NewsTicker", () => {
  it("shows the latest brief with its chart and the grouped stories", async () => {
    renderWithQuery(<NewsTicker symbol="tsm" />, {
      "/news/ticker/TSM": {
        as_of: ISO, available: true, symbol: "TSM",
        latest_brief: { id: 4, kind: "brief", subject: "TSM", posted_at: ISO, stage: "explained", critical: true, silent: false, has_chart: true,
          payload: { kind: "brief", title: "TSM brief", emoji: "📰", when: ISO, grid: [], links: [], updates: [], sections: [] } },
        clusters: [{ id: 1, headline: "TSMC beats on AI demand", source_count: 3, last_seen: ISO, links: [] }],
        next_earnings: null, request: null,
      },
      "/news/posts/4": { as_of: ISO, available: true, post: { id: 4 }, chart_data_uri: "data:image/png;base64,AAAA" },
    });
    expect(await screen.findByText("TSM brief")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /TSM chart/i })).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText("TSMC beats on AI demand")).toBeInTheDocument();
  });

  it("lists the stories in a titled card, each source a 44px link on a phone that says it opens a new tab", async () => {
    renderWithQuery(<NewsTicker symbol="TSM" />, {
      "/news/ticker/TSM": {
        as_of: ISO, available: true, symbol: "TSM", latest_brief: null, next_earnings: null, request: null,
        clusters: [
          { id: 1, headline: "TSMC beats on AI demand", source_count: 3, last_seen: ISO, links: [{ name: "Reuters", url: "https://r.example/1" }] },
          { id: 2, headline: "Fab delay in Arizona", source_count: 1, last_seen: ISO, links: [] },
        ],
      },
    });
    expect(await screen.findByRole("heading", { level: 2, name: "Recent stories" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Reuters (opens in a new tab)" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveClass("min-h-11", "md:min-h-0");
    expect(screen.getByText("3 sources")).toBeInTheDocument();
    expect(screen.getByText("1 source")).toBeInTheDocument();
  });

  it("says the next earnings with its timing", async () => {
    renderWithQuery(<NewsTicker symbol="NVDA" />, {
      "/news/ticker/NVDA": {
        as_of: ISO, available: true, symbol: "NVDA", latest_brief: null, clusters: [], request: null,
        next_earnings: { symbol: "NVDA", report_date: "2026-11-19", timing: "amc", eps_est: null, eps_actual: null, status: "scheduled", held: false },
      },
    });
    expect(await screen.findByText(/^Next earnings .* · AMC$/)).toBeInTheDocument();
  });

  it("says the news service has not run yet when unavailable", async () => {
    renderWithQuery(<NewsTicker symbol="NVDA" />, {
      "/news/ticker/NVDA": { as_of: ISO, available: false, symbol: "NVDA", latest_brief: null, clusters: [], next_earnings: null, request: null },
    });
    expect(await screen.findByText(/news service has not written anything yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/no brief yet/i)).not.toBeInTheDocument();
  });

  it("says it is loading, and says a failed read in words", async () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = render(<QueryClientProvider client={qc}><NewsTicker symbol="NVDA" /></QueryClientProvider>);
    expect(screen.getByRole("status", { name: "Loading NVDA news" })).toBeInTheDocument();
    unmount();
    renderWithQuery(<NewsTicker symbol="NVDA" />, {});
    expect(await screen.findByText("The news for NVDA could not be loaded. It is asked for again every minute.")).toBeInTheDocument();
  });
});
