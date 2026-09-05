import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { SummaryPanel } from "./SummaryPanel";

const SUMMARY = {
  thesis: "Steady compounder with rich premium.",
  bull_points: ["ROE above 15%", "Low debt"],
  bear_points: ["P/E above market"],
  watch_items: ["Earnings on 30 Oct"],
  caveats: [
    "This analysis is entirely quantitative. It cannot account for one-time charges.",
  ],
  model: "claude-sonnet-4-6",
  data_as_of: "2026-09-05T10:00:00Z",
};

function withProviders(node: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

function mockFetch(resp: any, status = 200) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    text: async () => "",
    json: async () => resp,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("SummaryPanel", () => {
  it("shows a Generate button and one line of text when no summary is cached", async () => {
    mockFetch({
      as_of: "2026-09-05T12:00:00Z",
      symbol: "AAPL",
      state: "unavailable",
      summary: null,
      reason: "No summary yet. Generate one on demand.",
    });
    render(withProviders(<SummaryPanel symbol="AAPL" />));
    expect(await screen.findByText(/No summary yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate summary/i })).toBeInTheDocument();
  });

  it("renders thesis, bulls, bears, watch items, and caveats as distinct labelled regions", async () => {
    mockFetch({
      as_of: "2026-09-05T12:00:00Z",
      symbol: "AAPL",
      state: "ready",
      summary: SUMMARY,
    });
    render(withProviders(<SummaryPanel symbol="AAPL" />));
    expect(await screen.findByText(SUMMARY.thesis)).toBeInTheDocument();
    expect(screen.getByText("Bull points")).toBeInTheDocument();
    expect(screen.getByText("ROE above 15%")).toBeInTheDocument();
    expect(screen.getByText("Bear points")).toBeInTheDocument();
    expect(screen.getByText("P/E above market")).toBeInTheDocument();
    expect(screen.getByText("Watch items")).toBeInTheDocument();
    expect(screen.getByText("Earnings on 30 Oct")).toBeInTheDocument();
    expect(screen.getByText("Caveats")).toBeInTheDocument();
    expect(
      screen.getByText(/entirely quantitative/i),
    ).toBeInTheDocument();
  });

  it("carries an attribution line naming the model and data as_of", async () => {
    mockFetch({
      as_of: "2026-09-05T12:00:00Z",
      symbol: "AAPL",
      state: "ready",
      summary: SUMMARY,
    });
    render(withProviders(<SummaryPanel symbol="AAPL" />));
    expect(await screen.findByText(/claude-sonnet-4-6/i)).toBeInTheDocument();
  });

  it("renders the caveats region even when present (never collapsed by default)", async () => {
    mockFetch({
      as_of: "2026-09-05T12:00:00Z",
      symbol: "AAPL",
      state: "ready",
      summary: SUMMARY,
    });
    render(withProviders(<SummaryPanel symbol="AAPL" />));
    expect(await screen.findByText("Caveats")).toBeInTheDocument();
    expect(screen.getByText(/one-time charges/i)).toBeInTheDocument();
  });

  it("shows a loading state on the button while generating", async () => {
    const fn = mockFetch({
      as_of: "2026-09-05T12:00:00Z",
      symbol: "AAPL",
      state: "unavailable",
      summary: null,
      reason: "No summary yet.",
    });
    // Make POST hang so isPending stays true.
    fn.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return new Promise(() => {});
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        text: async () => "",
        json: async () => ({
          as_of: "2026-09-05T12:00:00Z",
          symbol: "AAPL",
          state: "unavailable",
          summary: null,
          reason: "No summary yet.",
        }),
      });
    });
    render(withProviders(<SummaryPanel symbol="AAPL" />));
    const btn = await screen.findByRole("button", { name: /Generate summary/i });
    btn.click();
    expect(await screen.findByRole("button", { name: /Generating/i })).toBeInTheDocument();
    expect(btn).toBeDisabled();
  });

  it("shows the reason on a failed generation and leaves the rest of the page untouched", async () => {
    // POST /summary fails soft server-side: a 200 with state "pending" and a reason,
    // not an HTTP error (src/api/routers/research.py's post_summary contract).
    const fn = mockFetch({
      as_of: "2026-09-05T12:00:00Z",
      symbol: "AAPL",
      state: "unavailable",
      summary: null,
      reason: "No summary yet. Generate one on demand.",
    });
    fn.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () => "",
          json: async () => ({
            as_of: "2026-09-05T12:00:00Z",
            symbol: "AAPL",
            state: "pending",
            summary: null,
            reason: "Generation failed. The page is unaffected; try again later.",
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        text: async () => "",
        json: async () => ({
          as_of: "2026-09-05T12:00:00Z",
          symbol: "AAPL",
          state: "unavailable",
          summary: null,
          reason: "No summary yet. Generate one on demand.",
        }),
      });
    });
    render(withProviders(<SummaryPanel symbol="AAPL" />));
    const btn = await screen.findByRole("button", { name: /Generate summary/i });
    btn.click();
    expect(await screen.findByText(/Generation failed/i)).toBeInTheDocument();
    // The action to retry is still there — a failed generation doesn't wipe the panel.
    expect(screen.getByRole("button", { name: /Generate summary/i })).toBeInTheDocument();
  });
});