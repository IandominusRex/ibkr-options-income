import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ApiError } from "@/lib/api";

// The children have their own suites; here they are stand-ins that say where they were placed.
vi.mock("@/components/stock/PriceChart", () => ({
  PriceChart: ({ symbol, lines }: { symbol: string; lines: { title: string }[] }) => (
    <div data-testid="chart">{`${symbol} chart: ${lines.map((l) => l.title).join("; ")}`}</div>
  ),
}));
// The stand-in counts its mounts, so a test can tell a block that moved (a remount) from one that did not.
const valueMounts = vi.hoisted(() => ({ n: 0 }));
vi.mock("@/features/stock-value/ValueBlock", async () => {
  const { useEffect } = await import("react");
  return {
    ValueBlock: function ValueBlock({ symbol }: { symbol: string }) {
      useEffect(() => {
        valueMounts.n += 1;
      }, []);
      return <section aria-label={`Value book on ${symbol}`} data-testid="value" />;
    },
  };
});
vi.mock("@/features/market/NameNotes", () => ({ NameNotes: () => <section data-testid="notes" /> }));
vi.mock("@/components/stock/SummaryPanel", () => ({ SummaryPanel: () => <p>summary stand-in</p> }));

import { StockPage } from "./StockPage";

afterEach(cleanup);

const ready = <T,>(data: T) => ({ state: "ready", data, reason: null });

const ANALYSIS = {
  as_of: "2026-11-05T15:00:00Z",
  symbol: "GOOGL",
  name: "Alphabet Inc.",
  exchange: "NASDAQ",
  is_etf: false,
  quote: { value: 182.4, source: "ibkr", as_of: "2026-11-05T14:58:00Z", stale: true },
  fundamentals: { state: "unavailable", data: null, reason: "No filings for this symbol." },
  technicals: ready({ symbol: "GOOGL", price: 182.4, rsi_14: 55.2, atr_14: 3.1, macd: 0.5, macd_signal: 0.3, sma_20: 180, sma_50: 178, sma_200: 160, phase: "Stage 2", regime: "bull" }),
  sentiment: { state: "pending", data: null, reason: null },
  news: ready([]),
  checks: ready({ categories: [], warnings: [] }),
};

const VALUE_READY = {
  as_of: "2026-11-05T15:00:00Z", available: true, symbol: "GOOGL", computed: "stored", age_days: 1, plan: null,
  file: {
    symbol: "GOOGL", as_of: "2026-11-04", company_class: "operating", data_quality: "pass", health: "pass",
    ruleset_version: "v4", ruleset_hash: "be30d1eaa915",
    lists: [{
      list_name: "deep_value", baseline_verdict: "READY", verdict: "READY", decided_by: "python", fair_value: 215,
      effective_fair_value: 215, mos: 0.15, required_mos_pct: 30, entry_ceiling: 190, reasons: [], mos_review: false,
      methods: [], gates: [], size_pct: 3, tranches: 3,
    }],
  },
};

const VALUE_NO = {
  ...VALUE_READY,
  file: { ...VALUE_READY.file, lists: [{ ...VALUE_READY.file.lists[0], verdict: "NO", baseline_verdict: "NO" }] },
};

function headings() {
  return screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
}

function order(): string[] {
  // The value block's stand-in and the cards' titles, in DOM order.
  return Array.from(document.querySelectorAll("[data-testid=value], h2")).map((el) =>
    el.getAttribute("data-testid") === "value" ? "VALUE" : (el.textContent ?? ""),
  );
}

describe("StockPage", () => {
  it("leads with the ticker, its name, the last price with Delayed in words, and a back link to Research", async () => {
    renderWithQuery(<StockPage symbol="googl" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_READY });
    expect(await screen.findByText("Alphabet Inc. · NASDAQ")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("GOOGL");
    expect(screen.getByText("$182.40")).toBeInTheDocument();
    expect(screen.getByText("Delayed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("href", "/research");
    expect(screen.getByRole("button", { name: "Refresh GOOGL" })).toBeInTheDocument();
  });

  it("puts the value block first, under the chart, when the book would buy the name at a price, and draws its levels", async () => {
    renderWithQuery(<StockPage symbol="GOOGL" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_READY });
    expect(await screen.findByText("GOOGL chart: Fair value $215.00; Entry ceiling $190.00")).toBeInTheDocument();
    expect(order().slice(0, 3)).toEqual(["GOOGL price chart", "VALUE", "Checks"]);
  });

  it("holds the value block until the value book answers, then mounts it once in the slot the answer picks", async () => {
    let release: (v: unknown) => void = () => {};
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/research/GOOGL") return ANALYSIS;
      if (path === "/value/GOOGL") return new Promise((r) => (release = r));
      throw new Error(`unexpected fetch ${path}`);
    });
    valueMounts.n = 0;
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <StockPage symbol="GOOGL" />
      </QueryClientProvider>,
    );
    await screen.findByText("Alphabet Inc. · NASDAQ");
    expect(screen.queryByTestId("value")).toBeNull();
    release(VALUE_READY);
    await waitFor(() => expect(order().slice(0, 2)).toEqual(["GOOGL price chart", "VALUE"]));
    expect(valueMounts.n).toBe(1);
  });

  it("places the value block at the foot when the value book cannot be read", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/research/GOOGL") return ANALYSIS;
      throw new ApiError(500, "value.db unreadable");
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <StockPage symbol="GOOGL" />
      </QueryClientProvider>,
    );
    await screen.findByText("Alphabet Inc. · NASDAQ");
    await waitFor(() => expect(screen.getByTestId("value")).toBeInTheDocument());
    const o = order();
    expect(o.indexOf("VALUE")).toBe(o.indexOf("Financial statements") + 1);
  });

  it("puts the value block at the foot of the left column when every list is No", async () => {
    renderWithQuery(<StockPage symbol="GOOGL" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_NO });
    await screen.findByText("Alphabet Inc. · NASDAQ");
    expect(await screen.findByText("GOOGL chart:")).toBeInTheDocument();
    await screen.findByTestId("value");
    const o = order();
    expect(o.indexOf("VALUE")).toBe(o.indexOf("Financial statements") + 1);
  });

  it("shows each section in its own card, with the API's reason when it is not ready", async () => {
    renderWithQuery(<StockPage symbol="GOOGL" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_READY });
    await screen.findByText("Alphabet Inc. · NASDAQ");
    expect(headings()).toEqual(
      expect.arrayContaining(["Checks", "Technicals", "Financial statements", "News", "Sentiment", "Model summary"]),
    );
    expect(screen.getByText("No filings for this symbol.")).toBeInTheDocument();
    expect(screen.getByText("Building this section. It will appear shortly.")).toBeInTheDocument();
    expect(screen.getByText("RSI 14")).toBeInTheDocument();
  });

  it("sizes each column to one minmax(0,1fr) track, so a wide table inside a card scrolls and never widens the page on a phone", async () => {
    // Found by looking (Task 11): with the statements open, a grid with no column template took the
    // table's min-content width and the whole page scrolled sideways at 320 and 390 px.
    renderWithQuery(<StockPage symbol="GOOGL" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_READY });
    await screen.findByText("Alphabet Inc. · NASDAQ");
    const left = screen.getByTestId("chart").closest("section")?.parentElement;
    const right = screen.getByRole("heading", { level: 2, name: "News" }).closest("section")?.parentElement;
    expect(left).toHaveClass("grid-cols-1");
    expect(right).toHaveClass("grid-cols-1");
  });

  it("says a name the research service does not know in words, not an empty page", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      throw new ApiError(404, `Unknown ${path}`);
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <StockPage symbol="zzzz" />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText("The research service does not know ZZZZ. Check the ticker, or add it to the watchlist on Research."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Checks")).toBeNull();
  });
});
