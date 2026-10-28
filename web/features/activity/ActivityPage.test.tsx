import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetchMock } from "@/lib/test-query";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/activity",
}));

import { ActivityPage } from "./ActivityPage";

const now = () => new Date().toISOString();
const filters = { as_of: now(), symbol: null, strategy: null, outcome: null, since: null, until: null, book: "all" };

function serve() {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path.startsWith("/pnl/month")) {
      return {
        as_of: now(), book: "paper", spreads_available: true,
        pay: {
          month: "2026-10-01", strategy: "all", premium_collected: 0, bought_back: 0, commissions: 0,
          commissions_complete: true, net: 0, n_opened: 0, n_closed: 0, month_start_value: null, target_pct: null,
          target_mode: "off", target_amount: null, target_base: null, target: null, progress_pct: null, days_left: 8,
        },
      };
    }
    if (path.startsWith("/pnl/summary")) {
      return {
        as_of: now(), filters, marks_as_of: null,
        summary: { realized_total: 0, unrealized_total: null, commissions_complete: true, n_open: 0, n_closed: 0, win_rate: null, by_strategy: [], by_symbol: [], best: null, worst: null },
      };
    }
    if (path.startsWith("/pnl/equity")) return { as_of: now(), filters, curve: { points: [], gaps: [], starts_at: null } };
    if (path.startsWith("/pnl/ledger")) return { as_of: now(), filters, campaigns: [], marks_as_of: null, n_legs: 0 };
    if (path.startsWith("/ledger/summary")) {
      return {
        as_of: now(),
        summary: {
          total_realized_usd: 0, interest_and_fees_usd: 0, contributed_usd: null, capital_utilised_usd: 0, available_usd: null,
          unrealized_usd: null, win_rate: null, n_trades: 0, n_open: 0, premium_this_month_usd: 0, months: [], curve: [],
          by_strategy: [], by_book: [], upcoming: [], fx_incomplete: false, orphan_closes: 0, unreviewed_corporate_actions: 0, marks_as_of: null,
        },
      };
    }
    if (path.startsWith("/ledger/tickers")) return { as_of: now(), tickers: [] };
    if (path.startsWith("/options/orders")) return { as_of: now(), orders: [] };
    if (path.startsWith("/options/fills")) return { as_of: now(), fills: [] };
    if (path.startsWith("/options/controls")) return {};
    if (path.startsWith("/spreads/orders")) return { as_of: now(), available: true, underlying: "SPY", orders: [] };
    if (path.startsWith("/ledger/executions")) return { as_of: now(), days: 30, limit: 200, truncated: false, executions: [] };
    if (path.startsWith("/pnl/system")) {
      return {
        as_of: now(), since: null, until: null,
        report: { n_closed: 0, period_start: null, period_end: null, blended_score_buckets: [], component_buckets: [], signal_correlations: [], notes: ["Read-only."] },
        agreement: { n_closed: 0, n_agreed: 0, agreement_rate: null, claude_win_rate: null, baseline_win_rate: null },
      };
    }
    if (path.startsWith("/pnl/sizing")) return { as_of: now(), since: null, groups: [] };
    if (path.startsWith("/claude/context")) return { available: false, dossiers: [] };
    throw new Error(`no mocked response for ${path}`);
  });
}

const mount = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // A function, so each rerender is a new element: React skips an identical one.
  const tree = () => (
    <QueryClientProvider client={qc}>
      <ActivityPage />
    </QueryClientProvider>
  );
  const r = render(tree());
  return { rerenderPage: () => r.rerender(tree()) };
};

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
  serve();
});

describe("ActivityPage", () => {
  it("opens on Pay, with the four view chips", async () => {
    mount();
    expect(screen.getByRole("heading", { level: 1, name: "Activity" })).toBeInTheDocument();
    const views = screen.getByRole("group", { name: "View" });
    expect(within(views).getByRole("button", { name: "Pay" })).toHaveAttribute("aria-pressed", "true");
    for (const name of ["Ledger", "Fills and orders", "System"]) {
      expect(within(views).getByRole("button", { name })).toHaveAttribute("aria-pressed", "false");
    }
    expect(await screen.findByRole("group", { name: /pay stub$/ })).toBeInTheDocument();
  });

  it.each([
    ["ledger", /What IBKR reports, from the live feed/],
    ["fills", /The system's record: the wheel orders it sent to IBKR/],
    ["system", /A positive number is what the held-back contracts would have earned/],
  ])("opens the %s view the URL asks for", async (view, text) => {
    nav.params = new URLSearchParams(`view=${view}`);
    mount();
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("opens Pay for a view it does not know", async () => {
    nav.params = new URLSearchParams("view=bogus");
    mount();
    expect(await screen.findByRole("group", { name: /pay stub$/ })).toBeInTheDocument();
  });

  it("writes the chosen view into the URL and keeps the month", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    mount();
    await screen.findByRole("group", { name: /pay stub$/ });
    fireEvent.click(screen.getByRole("button", { name: "Ledger" }));
    expect(nav.replace).toHaveBeenCalledWith("/activity?month=2026-09&view=ledger", { scroll: false });
  });

  it("changes view without asking for the other views' data", async () => {
    // The mock's call log spans the whole file, so look only at the calls this test makes.
    const start = apiFetchMock.mock.calls.length;
    const askedForExecutions = () =>
      apiFetchMock.mock.calls.slice(start).some((c) => String(c[0]).startsWith("/ledger/executions"));
    const page = mount();
    await screen.findByRole("group", { name: /pay stub$/ });
    expect(askedForExecutions()).toBe(false);
    nav.params = new URLSearchParams("view=system");
    page.rerenderPage();
    await screen.findByText(/A positive number is what the held-back contracts would have earned/);
    expect(askedForExecutions()).toBe(false);
  });
});
