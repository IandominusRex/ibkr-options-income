import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/lib/test-query";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/",
}));
vi.mock("./HeroChart", () => ({ HeroChart: () => <div data-testid="chart" /> }));

import { HomePage } from "./HomePage";

const responses = {
  "/portfolio/value": {
    as_of: "",
    series: { range: "1m", points: [], latest: 248310.42, latest_at: null, previous_close: null, change_today: null, change_today_pct: null },
  },
  "/pnl/month": {
    as_of: "",
    book: "paper",
    spreads_available: true,
    pay: { month: "2026-10-01", strategy: "all", premium_collected: 0, bought_back: 0, commissions: 0, commissions_complete: true, net: 0, n_opened: 0, n_closed: 0, month_start_value: null, target_pct: null, target_mode: "off", target_amount: null, target_base: null, target: null, progress_pct: null, days_left: 18 },
  },
  "/pnl/day": { as_of: "", date: "2026-10-15", book: "paper", strategy: "all", trades: [], spreads_available: true },
  "/options/shorts": { as_of: "", shorts: [] }, "/portfolio/positions": { as_of: "", source: "none", degraded: true, groups: [] },
  "/spreads/positions": { as_of: "", available: false, underlying: "SPY", mode: "paper", positions: [] },
  "/options/approvals": { as_of: "", approvals: [] },
  "/value/book": { as_of: "", available: false, enabled: false, positions: [], proposals: [], funding: [], release_max_closes: 2 },
  "/options/controls": { as_of: "", autonomy: { level: "a", label: "A" }, rungs: [], halted: false, halt_reason: null, halted_at: null, mode: "paper", drain_healthy: true, drain_last_seen: null, pending_commands: 0 },
};

describe("HomePage", () => {
  it("puts the strategy switcher first, then the hero, pay and positions", async () => {
    renderWithQuery(<HomePage />, responses);
    const switcher = await screen.findByRole("group", { name: "Strategy" });
    const hero = await screen.findByRole("region", { name: "Account value" });
    const pay = await screen.findByRole("button", { name: /October pay/ });
    const positions = await screen.findByRole("heading", { name: "Positions" });
    const order = [switcher, hero, pay, positions];
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });
  it("puts the Value book card right after Positions, under All only", async () => {
    nav.params = new URLSearchParams();
    renderWithQuery(<HomePage />, responses);
    const positions = await screen.findByRole("heading", { name: "Positions" });
    const value = await screen.findByRole("heading", { name: "Value book" });
    expect(positions.compareDocumentPosition(value) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await screen.findByText("The value book has not written anything yet.")).toBeInTheDocument();
    cleanup();
    nav.params = new URLSearchParams("strategy=csp");
    renderWithQuery(<HomePage />, responses);
    await screen.findByRole("heading", { name: "Positions" });
    expect(screen.queryByRole("heading", { name: "Value book" })).toBeNull();
    nav.params = new URLSearchParams();
  });
  it("puts Done today under Positions on a phone, where it is the page's last card", async () => {
    renderWithQuery(<HomePage />, responses);
    const positions = await screen.findByRole("heading", { name: "Positions" });
    const today = await screen.findByRole("heading", { name: "Done today" });
    expect(positions.compareDocumentPosition(today) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await screen.findByText("Nothing has traded yet today.")).toBeInTheDocument();
  });
  it("names the page with one level-1 heading, so the card headings sit under it", async () => {
    renderWithQuery(<HomePage />, responses);
    expect(await screen.findByRole("heading", { level: 1, name: "Home" })).toBeInTheDocument();
  });
  it("writes the strategy into the URL", async () => {
    renderWithQuery(<HomePage />, responses);
    // Scoped to the page's switcher: the positions card carries a "CSPs" chip of its own.
    const switcher = await screen.findByRole("group", { name: "Strategy" });
    fireEvent.click(within(switcher).getByRole("button", { name: "CSPs" }));
    expect(nav.replace).toHaveBeenCalledWith("/?strategy=csp", { scroll: false });
  });
  it("hydrates over the server HTML even when the rail has already filled the shared cache", async () => {
    // React hydrates Home's Suspense boundary after the rail, and the rail's approvals query
    // (same key) can land first; Home's first client render must still match the server's.
    const wrap = (qc: QueryClient) => (
      <QueryClientProvider client={qc}>
        <HomePage />
      </QueryClientProvider>
    );
    const html = renderToString(wrap(new QueryClient()));
    const container = document.createElement("div");
    container.innerHTML = html;
    document.body.appendChild(container);
    const warm = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    warm.setQueryData(["options", "approvals", "pending"], {
      as_of: "",
      approvals: [
        {
          as_of: "",
          id: 1,
          candidate_id: "c1",
          status: "pending",
          underlying: "AAPL",
          strategy: "cash_secured_put",
          right: "P",
          strike: 180,
          expiry: "2099-11-21",
          contracts: 1,
          premium: 2.35,
          blended_score: 0.7,
          created_at: "2026-10-13T13:00:00Z",
          expires_at: null,
          decided_at: null,
          order_state: null,
          source: "scan",
          review: null,
          rationale_tags: [],
        },
      ],
    });
    const errors: unknown[] = [];
    await act(async () => {
      hydrateRoot(container, wrap(warm), { onRecoverableError: (e) => errors.push(e) });
    });
    expect(errors).toEqual([]);
    container.remove();
  });
  describe("the Value kind", () => {
    const proposal = (id: number, over: Record<string, unknown> = {}) => ({
      id, kind: "buy", symbol: "GOOGL", list_name: "quality_growth", shares: 10, price: 180, reason: "tranche 1",
      cause: "python", needs_tap: true, status: "pending", fingerprint: `fp${id}`, expires_at: "2099-01-01T00:00:00Z", ...over,
    });
    const book = (proposals: unknown[]) => ({
      ...responses["/value/book"], available: true, enabled: true, ceiling_usd: 30000, used_usd: 0, proposals,
    });

    it("lists Value last in the switcher with the proposals waiting on a tap", async () => {
      renderWithQuery(<HomePage />, {
        ...responses,
        "/value/book": book([proposal(1), proposal(2), proposal(3, { needs_tap: false, status: "approved" })]),
      });
      const switcher = await screen.findByRole("group", { name: "Strategy" });
      const names = within(switcher).getAllByRole("button").map((b) => b.textContent);
      expect(names[names.length - 1]).toMatch(/^Value/);
      expect(await within(switcher).findByRole("button", { name: "Value 2" })).toBeInTheDocument();
    });
    it("shows no count when nothing waits on a tap, and none when the book cannot be read", async () => {
      renderWithQuery(<HomePage />, { ...responses, "/value/book": book([proposal(1, { needs_tap: false, status: "approved" })]) });
      const switcher = await screen.findByRole("group", { name: "Strategy" });
      expect(await within(switcher).findByRole("button", { name: "Value" })).toBeInTheDocument();
      cleanup();
      renderWithQuery(<HomePage />, responses);
      const again = await screen.findByRole("group", { name: "Strategy" });
      expect(within(again).getByRole("button", { name: "Value" })).toBeInTheDocument();
    });
    it("writes value into the URL", async () => {
      nav.replace.mockClear();
      renderWithQuery(<HomePage />, responses);
      const switcher = await screen.findByRole("group", { name: "Strategy" });
      fireEvent.click(within(switcher).getByRole("button", { name: "Value" }));
      expect(nav.replace).toHaveBeenCalledWith("/?strategy=value", { scroll: false });
    });
    it("shows the Value book card under Value, and points Needs you at it", async () => {
      nav.params = new URLSearchParams("strategy=value");
      renderWithQuery(<HomePage />, { ...responses, "/value/book": book([proposal(1)]) });
      expect(await screen.findByRole("heading", { name: "Value book" })).toBeInTheDocument();
      expect(await screen.findByText("Value proposals wait in the Value book card.")).toBeInTheDocument();
      expect(screen.queryByText("Nothing needs you right now.")).toBeNull();
      nav.params = new URLSearchParams();
    });
  });
});
