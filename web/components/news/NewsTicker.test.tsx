import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { NewsTicker } from "./NewsTicker";

const ISO = new Date().toISOString();

describe("NewsTicker", () => {
  it("shows the latest brief and the request button", async () => {
    renderWithQuery(<NewsTicker symbol="tsm" />, {
      "/news/ticker/TSM": {
        as_of: ISO, available: true, symbol: "TSM",
        latest_brief: { id: 4, kind: "brief", subject: "TSM", posted_at: ISO, stage: "explained", critical: true, silent: false, has_chart: true,
          payload: { kind: "brief", title: "TSM brief", emoji: "📰", when: ISO, grid: [], links: [], updates: [], sections: [] } },
        clusters: [{ id: 1, headline: "TSMC beats on AI demand", source_count: 3, last_seen: ISO, links: [] }],
        next_earnings: null, request: null,
      },
      "/news/posts/4": { as_of: ISO, available: true, post: { id: 4 }, chart_data_uri: "data:image/png;base64,AAAA" },
      "/options/controls": { drain_healthy: true },
    });
    expect(await screen.findByText("TSM brief")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /request fresh brief/i })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /TSM chart/i })).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText("TSMC beats on AI demand")).toBeInTheDocument();
  });

  it("submits a news_brief command for the symbol and shows the receipt", async () => {
    renderWithQuery(<NewsTicker symbol="tsm" />, {
      "/news/ticker/TSM": {
        as_of: ISO, available: true, symbol: "TSM", latest_brief: null, clusters: [], next_earnings: null, request: null,
      },
      "/commands": {
        id: 7, kind: "news_brief", status: "pending", result: null, needs_confirmation: false, confirm_token: null,
        created_at: ISO, applied_at: null, as_of: ISO, created: true,
      },
      "/options/controls": { drain_healthy: true },
    });
    expect(await screen.findByText(/no brief yet/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /request fresh brief/i }));
    await vi.waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === "/commands" && JSON.parse(String((c[1] as RequestInit).body)).kind === "news_brief"
            && JSON.parse(String((c[1] as RequestInit).body)).payload.symbol === "TSM",
        ),
      ).toBe(true),
    );
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /request fresh brief/i })).toBeDisabled());
  });

  it("says the news service has not run yet when unavailable", async () => {
    renderWithQuery(<NewsTicker symbol="NVDA" />, {
      "/news/ticker/NVDA": { as_of: ISO, available: false, symbol: "NVDA", latest_brief: null, clusters: [], next_earnings: null, request: null },
      "/options/controls": { drain_healthy: true },
    });
    expect(await screen.findByText(/news service has not written anything yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/no brief yet/i)).not.toBeInTheDocument();
  });
});
