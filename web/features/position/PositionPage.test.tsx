import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";

const chart = vi.hoisted(() => ({
  data: [] as Array<Array<{ time: number; value: number }>>,
  lines: [] as Array<{ price: number; title: string; lineStyle: number }>,
  markers: [] as Array<Array<{ text?: string; time: number }>>,
  options: [] as Array<{ layout?: { attributionLogo?: boolean } }>,
}));

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  CrosshairMode: { Magnet: 1 },
  LineStyle: { Dashed: 2 },
  createChart: (_el: unknown, opts: { layout?: { attributionLogo?: boolean } }) => {
    chart.options.push(opts);
    return {
      addLineSeries: () => ({
        setData: (d: Array<{ time: number; value: number }>) => chart.data.push(d),
        createPriceLine: (l: { price: number; title: string; lineStyle: number }) => {
          chart.lines.push(l);
          return { applyOptions: vi.fn() };
        },
        setMarkers: (m: Array<{ text?: string; time: number }>) => chart.markers.push(m),
        applyOptions: vi.fn(),
      }),
      subscribeCrosshairMove: vi.fn(),
      timeScale: () => ({ fitContent: vi.fn() }),
      applyOptions: vi.fn(),
      remove: vi.fn(),
    };
  },
}));

import { PositionPage } from "./PositionPage";
import type { PositionDetail } from "./types";

beforeEach(() => {
  chart.data.length = 0;
  chart.lines.length = 0;
  chart.markers.length = 0;
  chart.options.length = 0;
});
afterEach(cleanup);

const SLUG = "2099-01-15_P180";

// Daily closes: one a day for 400 days ending 2026-10-14, so every range has bars.
const BARS = (() => {
  const out = [];
  const end = Date.UTC(2026, 9, 14);
  for (let i = 400; i >= 0; i--) {
    const t = new Date(end - i * 86_400_000).toISOString().slice(0, 10);
    out.push({ time: t, open: 170, high: 190, low: 160, close: 170 + (400 - i) * 0.035, volume: 1 });
  }
  return out;
})();
const bars = { as_of: "", bars: BARS };

const headlines = {
  as_of: "",
  symbol: "AAPL",
  items: [
    { title: "Apple unveils a new chip", url: "https://news.example/1", published_at: "2026-10-14T12:00:00Z", source: "Wire", sentiment: 0.5 },
    { title: "Regulator opens a probe", url: null, published_at: null, source: null, sentiment: null },
  ],
};

function detail(over: Partial<PositionDetail> = {}): PositionDetail {
  return {
    as_of: "2026-10-15T14:00:00Z",
    underlying: "AAPL",
    slug: SLUG,
    kind: "option",
    held: true,
    source: "monitor",
    degraded: false,
    option: {
      as_of: "", symbol: "x", right: "P", strike: 180, expiry: "2099-01-15", dte: 39, contracts: 1, short: true,
      delta: -0.2, delta_source: "ibkr", market_price: 0.62, market_value: -62, unrealized_pnl: 173,
      moneyness: "otm", assignment_risk: false,
    },
    stock: null,
    campaign: null,
    spread: null,
    opened: {
      key: "c1:opened", action: "opened", how: null, kind: "csp", source: "wheel", underlying: "AAPL", right: "P", strike: 180,
      long_strike: null, expiry: "2099-01-15", contracts: 1, at: "2026-10-03T14:42:00Z", is_live: false, premium: 235,
      bought_back: null, commissions: 1.3, commissions_complete: true, net_pnl: null, capital: 18000, roc_pct: 1.3056,
      annualized_pct: 12.2, pct_kept: null, dte_at_open: 42, days_held: null, reason: null, facts: [], approval_id: 7,
      review: {
        why_attractive: "IV rank 62.", risks: "Earnings inside.", tradeoffs: "", assignment_considerations: "",
        rolling_considerations: "", recommendation: "sell", priority: 1, confidence: 0.7, summary: "Fine.", evidence: [],
      },
      rolled_to: null,
    },
    closed: null,
    spreads_available: true,
    ...over,
  } as PositionDetail;
}

const serve = (d: PositionDetail = detail(), extra: Record<string, unknown> = {}) => ({
  [`/portfolio/positions/AAPL/${d.slug}`]: d,
  "/research/AAPL/bars?range=1y": bars,
  "/research/AAPL/headlines": headlines,
  "/options/shorts": { as_of: "", shorts: [] },
  "/options/controls": {
    as_of: "", autonomy: { level: "approve", label: "Approve each trade" }, rungs: [], halted: false,
    halt_reason: null, halted_at: null, mode: "paper", drain_healthy: true, drain_last_seen: null,
    pending_commands: 0,
  },
  ...extra,
});

describe("PositionPage", () => {
  it("names the contract, its status, and when it was sold", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    expect(await screen.findByRole("heading", { level: 1, name: "AAPL $180 put" })).toBeInTheDocument();
    expect(screen.getByText("Out of the money")).toBeInTheDocument();
    expect(screen.getByText("Expires Thu, Jan 15 · sold Sat, Oct 3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Home/ })).toHaveAttribute("href", "/");
  });

  it("puts the chart first, then the trade, then the headlines, which is the phone's order", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    const chartEl = await screen.findByRole("region", { name: "AAPL price chart" });
    const trade = await screen.findByRole("article");
    const news = await screen.findByRole("heading", { name: "AAPL headlines" });
    const follows = (a: Element, b: Element) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(follows(chartEl, trade)).toBe(true);
    expect(follows(trade, news)).toBe(true);
  });

  it("shows the initial trade as it was opened: premium, commission, what is held, a year, Claude's review", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    const stub = await screen.findByRole("group", { name: "AAPL opened math" });
    expect(within(stub).getByText("+$235.00")).toBeInTheDocument();
    expect(within(stub).getByText("−$1.30")).toBeInTheDocument();
    expect(within(stub).getByText("On $18,000.00 held")).toBeInTheDocument();
    expect(within(stub).getByText("1.31%")).toBeInTheDocument();
    expect(screen.getByText("Opened · Cash-secured put")).toBeInTheDocument();
    expect(screen.getByText("Sat, Oct 3")).toBeInTheDocument(); // a date, not a clock time
    expect(screen.getByRole("button", { name: /Why this trade/ })).toHaveTextContent("Claude's review");
    expect(screen.getByRole("link", { name: "Details" })).toHaveAttribute("href", "/trades/7");
  });

  it("says where it stands now, from the snapshot and the chart's last close", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    const now = await screen.findByRole("region", { name: "Now" });
    expect(within(now).getByText("+$173.00")).toBeInTheDocument();
    expect(within(now).getByText("74%")).toBeInTheDocument();
    expect(within(now).getByText("39 days")).toBeInTheDocument();
    // the chart's last close is 170 + 400 * 0.035 = $184
    expect(await within(now).findByText("$184.00, 2.2% above the strike")).toBeInTheDocument();
  });

  it("draws the strike across the underlying's chart and marks the day it was sold", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    await screen.findByRole("img", { name: /AAPL closing price over 3M/ });
    expect(chart.lines).toEqual([expect.objectContaining({ price: 180, title: "Strike $180", lineStyle: 2 })]);
    expect(chart.markers.at(-1)?.[0].text).toBe("Sold");
    expect(chart.options.at(-1)?.layout?.attributionLogo).toBe(false);
    expect(screen.getByRole("img", { name: /Strike \$180/ })).toBeInTheDocument();
  });

  it("switches the chart's range without another request", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    await screen.findByRole("img", { name: /over 3M/ });
    const three = chart.data.at(-1)!.length;
    const barRequests = () => apiFetchMock.mock.calls.filter((c) => String(c[0]).startsWith("/research/AAPL/bars")).length;
    const before = barRequests();
    fireEvent.click(screen.getByRole("button", { name: "1Y" }));
    await screen.findByRole("img", { name: /over 1Y/ });
    expect(chart.data.at(-1)!.length).toBeGreaterThan(three);
    expect(barRequests()).toBe(before);
  });

  it("lists the headlines newest first with their sentiment in words, links in a new tab", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    const link = await screen.findByRole("link", { name: /Apple unveils a new chip/ });
    expect(link).toHaveAttribute("href", "https://news.example/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByText("bullish")).toBeInTheDocument();
    expect(screen.getByText("Regulator opens a probe")).toBeInTheDocument(); // no url: plain text
    expect(screen.getByText("n/a")).toHaveClass("hatch"); // unknown sentiment is unknown, with texture
  });

  it("makes a headline link a 44px target on a phone, inline from 768px", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    const link = await screen.findByRole("link", { name: /Apple unveils a new chip/ });
    expect(link).toHaveClass("min-h-11", "md:inline", "md:min-h-0");
  });

  it("sizes the trade column to one minmax(0,1fr) track, so a wide child never widens the page", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    const trade = await screen.findByRole("article");
    expect(trade.parentElement).toHaveClass("grid-cols-1", "min-w-0");
  });

  it("says so when there are no headlines, or they cannot load", async () => {
    const { unmount } = renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve(detail(), { "/research/AAPL/headlines": { as_of: "", symbol: "AAPL", items: [] } }));
    expect(await screen.findByText("No recent headlines for AAPL.")).toBeInTheDocument();
    unmount();
    cleanup();
    const broken = serve();
    delete (broken as Record<string, unknown>)["/research/AAPL/headlines"];
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, broken);
    expect(await screen.findByText("Headlines are unavailable right now.")).toBeInTheDocument();
  });

  it("a contract no longer held shows how it ended instead of a Now card", async () => {
    const closed = {
      ...detail().opened!, key: "c1:closed", action: "closed", how: "bought_back", at: "2026-10-14T15:00:00Z",
      premium: 235, bought_back: 62, commissions: 2.6, net_pnl: 170.4, pct_kept: 73.6,
      reason: "Closed for a profit: the position reached its profit target.",
      facts: [{ label: "Rule", text: "The system buys a short back once enough premium is kept.", source: "system" }], review: null,
    } as never;
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve(detail({ held: false, option: null, closed })));
    expect(await screen.findByText("No longer held")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Now" })).toBeNull();
    expect(screen.getByText("Closed for a profit: the position reached its profit target.")).toBeInTheDocument();
    const stub = screen.getByRole("group", { name: "AAPL closed math" });
    expect(within(stub).getByText("+$170.40")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "AAPL $180 put" })).toBeInTheDocument();
  });

  it("says plainly when the system never opened the position", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve(detail({ opened: null })));
    expect(await screen.findByText(/not opened by the system/)).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Now" })).toBeInTheDocument();
  });

  it("shows shares with their cost basis and the wheel behind them, and draws the cost lines", async () => {
    const shares = detail({
      kind: "shares",
      slug: "shares",
      option: null,
      opened: null,
      stock: { as_of: "", shares: 100, avg_cost: 181, adjusted_cost_basis: 176.5, market_price: 184, market_value: 18400, unrealized_pnl: 300, unrealized_pnl_adjusted: 750 },
      campaign: { campaign_id: "AAPL-1", symbol: "AAPL", status: "open", opened_date: "2026-09-20", closed_date: null, total_premium_collected: 450, total_debit_paid: 0, net_premium: 450, assigned: true, adjusted_cost_basis: 176.5, realized_stock_pnl: null } as never,
    });
    renderWithQuery(<PositionPage underlying="AAPL" slug="shares" />, serve(shares));
    expect(await screen.findByRole("heading", { level: 1, name: "AAPL · 100 shares" })).toBeInTheDocument();
    expect(screen.getByText("Held since Sun, Sep 20")).toBeInTheDocument();
    expect(screen.getByText("Adjusted cost (premium counted)")).toBeInTheDocument();
    const wheel = screen.getByRole("group", { name: "AAPL wheel premium" });
    expect(within(wheel).getAllByText("+$450.00")).toHaveLength(2);
    await screen.findByRole("img", { name: /Avg cost \$181; Adjusted \$176.5/ });
    expect(chart.lines.map((l) => l.title)).toEqual(["Avg cost $181", "Adjusted $176.5"]);
  });

  it("says a position is unknown on a 404, and that it could not load otherwise", async () => {
    const renderFailing = (error: ApiError) => {
      apiFetchMock.mockImplementation(async () => {
        throw error;
      });
      const qc = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
      return render(
        <QueryClientProvider client={qc}>
          <PositionPage underlying="AAPL" slug="2099-01-15_P999" />
        </QueryClientProvider>,
      );
    };
    const { unmount } = renderFailing(new ApiError(404, "No such position"));
    expect(await screen.findByText(/There is no record of this position/)).toBeInTheDocument();
    // a 404 is not retried: it would not change in a minute
    expect(apiFetchMock.mock.calls.filter((c) => String(c[0]).includes("2099-01-15_P999"))).toHaveLength(1);
    unmount();
    renderFailing(new ApiError(502, "boom"));
    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument();
  });

  it("holds its place while loading", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    expect(screen.getByRole("status", { name: "Loading the position" })).toBeInTheDocument();
    await screen.findByRole("heading", { level: 1, name: "AAPL $180 put" });
  });

  it("offers Propose a roll on a held short option", async () => {
    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
    expect(await screen.findByRole("button", { name: "Propose a roll" })).toBeInTheDocument();
  });

  it("offers no roll for a long option, a contract no longer held, or one whose strike is unknown", async () => {
    const held = detail();
    const cases = [
      detail({ option: { ...held.option!, short: false } }),
      detail({ held: false, option: null }),
      detail({ option: { ...held.option!, strike: null } }),
    ];
    for (const d of cases) {
      const { unmount } = renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve(d));
      await screen.findByRole("heading", { level: 1 });
      expect(screen.queryByRole("button", { name: "Propose a roll" })).toBeNull();
      unmount();
    }
  });
});
