import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { todayInNewYork } from "@/features/trades/time";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/activity",
}));

import { currentMonth } from "./month";
import { PayView } from "./PayView";

const now = () => new Date().toISOString();
const pay = (over: Record<string, unknown> = {}) => ({
  month: "2026-09-01", strategy: "all", premium_collected: 2000, bought_back: 400, commissions: 26,
  commissions_complete: true, net: 1574, n_opened: 12, n_closed: 9, month_start_value: 100000,
  target_pct: null, target_mode: "off", target_amount: null, target_base: null, target: null,
  progress_pct: null, days_left: 8, ...over,
});
const monthBody = (over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
  as_of: now(), book: "paper", pay: pay(over), spreads_available: true, ...extra,
});
const filters = { as_of: now(), symbol: null, strategy: null, outcome: null, since: null, until: null, book: "all" };
const summary = (over: Record<string, unknown> = {}) => ({
  as_of: now(), filters, marks_as_of: now(),
  summary: {
    realized_total: 320, unrealized_total: 115, commissions_complete: true, n_open: 2, n_closed: 4,
    win_rate: 0.75, by_strategy: [], by_symbol: [], best: null, worst: null, ...over,
  },
});
const equity = (startsAt: string | null = "2026-06-24") => ({
  as_of: now(), filters, curve: { points: [], gaps: [], starts_at: startsAt },
});
const leg = (over: Record<string, unknown> = {}) => ({
  candidate_id: "cand-1", campaign_id: null, symbol: "NVDA 261016 00170000P", underlying: "NVDA",
  strategy: "cash_secured_put", right: "P", strike: 170, expiry: "2026-10-16", contracts: 1,
  opened_at: now(), closed_at: null, credit: 150, debit: 0, commissions: 1, commissions_complete: true,
  net_pnl: null, unrealized_pnl: null, days_held: 5, roc_pct: 0.88, annualized_pct: null,
  outcome: "still_open", is_live: false, ...over,
});
const campaign = (over: Record<string, unknown> = {}) => ({
  campaign_id: "camp-1", symbol: "NVDA", status: "open", opened_date: "2026-09-01", closed_date: null,
  legs: [leg()], option_realized: 0, option_unrealized: 115, stock_realized: null, stock_unrealized: null,
  assigned: false, adjusted_cost_basis: null, total_net: 115, ...over,
});
const ledgerBody = (campaigns: unknown[] = []) => ({
  as_of: now(), filters, campaigns, marks_as_of: null, n_legs: campaigns.length,
});
const serve = (month: unknown = monthBody(), eq: unknown = equity()) =>
  renderWithQuery(<PayView />, {
    "/pnl/month": month,
    "/pnl/summary": summary(),
    "/pnl/equity": eq,
    "/pnl/ledger": ledgerBody(),
  });
const calls = () => apiFetchMock.mock.calls.map((c) => String(c[0]));

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
});

describe("PayView", () => {
  it("shows this month's stub, open, with the pace sentence and the days left", async () => {
    serve();
    const current = currentMonth(todayInNewYork());
    const stub = await screen.findByRole("group", { name: /pay stub$/ });
    expect(within(stub).getByText("Premium collected")).toBeInTheDocument();
    expect(within(stub).getByText("Net so far")).toBeInTheDocument();
    expect(within(stub).getByText("+$1,574.00")).toBeInTheDocument();
    expect(screen.getByText("No target set · 8 days left")).toBeInTheDocument();
    expect(calls()).toContain(`/pnl/month?month=${current}&strategy=all`);
  });

  it("reads the month from the URL and asks the API for it, with no days left on a past month", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve();
    expect(await screen.findByRole("heading", { name: "September 2026 pay" })).toBeInTheDocument();
    expect(calls()).toContain("/pnl/month?month=2026-09&strategy=all");
    const stub = await screen.findByRole("group", { name: "September 2026 pay stub" });
    expect(within(stub).getByText("Net for the month")).toBeInTheDocument();
    expect(screen.getByText("No target set")).toBeInTheDocument();
    expect(screen.queryByText(/days left/)).toBeNull();
  });

  it("says so when nothing happened in a month, over a stub of genuine zeros", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve(monthBody({ premium_collected: 0, bought_back: 0, commissions: 0, net: 0, n_opened: 0, n_closed: 0 }));
    expect(await screen.findByText("Nothing was opened or closed in September 2026.")).toBeInTheDocument();
    const stub = screen.getByRole("group", { name: "September 2026 pay stub" });
    expect(within(stub).getAllByText("$0").length).toBeGreaterThan(0);
  });

  it("shows the target, the meter and the percent for a past month", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve(monthBody({ target_mode: "fixed", target: 2000, target_amount: 2000, progress_pct: 78.7 }));
    expect(await screen.findByText("79% of target")).toBeInTheDocument();
    expect(screen.getByText("of $2,000.00")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "September 2026 target" })).toHaveAttribute("aria-valuenow", "79");
  });

  it("says the target cannot be worked out without the month's opening value", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve(monthBody({ target_mode: "pct_of_account", target_pct: 2, target: null, progress_pct: null }));
    expect(await screen.findByText(/needs the month's opening account value/)).toBeInTheDocument();
  });

  it("steps to the month before, and back to this month", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve();
    await screen.findByRole("heading", { name: "September 2026 pay" });
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/activity?month=2026-08", { scroll: false });
    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/activity", { scroll: false });
  });

  it("offers no month after this one", async () => {
    serve();
    await screen.findByRole("group", { name: /pay stub$/ });
    expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
  });

  it("stops going back at the month the system began", async () => {
    nav.params = new URLSearchParams("month=2026-06");
    serve(monthBody(), equity("2026-06-24"));
    await screen.findByRole("heading", { name: "June 2026 pay" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Previous month" })).toBeDisabled());
  });

  it("flags that spread income is unavailable, and says the total leaves it out", async () => {
    serve(monthBody({}, { spreads_available: false }));
    expect(await screen.findByText("Spreads unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Spread income is unavailable because the spreads database could not be read, so this total leaves it out."),
    ).toBeInTheDocument();
  });

  it("says it could not load, and that it tries again", async () => {
    renderWithQuery(<PayView />, { "/pnl/summary": summary(), "/pnl/equity": equity() });
    expect(await screen.findByText("Could not load this month's pay.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every minute.")).toBeInTheDocument();
  });

  it("puts the totals since the system began under the month", async () => {
    serve();
    expect(await screen.findByRole("heading", { name: "Since the system began" })).toBeInTheDocument();
    expect(await screen.findByText("Realized total")).toBeInTheDocument();
  });

  it("narrows the totals, the curve and the legs by one set of filters, and the CSV carries them", async () => {
    serve();
    fireEvent.change(await screen.findByLabelText("Symbol"), { target: { value: "nvda" } });
    await waitFor(() => {
      expect(calls()).toContain("/pnl/summary?book=all&symbol=NVDA");
      expect(calls()).toContain("/pnl/equity?book=all&symbol=NVDA");
      expect(calls()).toContain("/pnl/ledger?book=all&symbol=NVDA");
    });
    expect(screen.getByTestId("ledger-export-link")).toHaveAttribute("href", "/api/pnl/ledger.csv?book=all&symbol=NVDA");
  });

  it("says the filters apply to everything under them", async () => {
    serve();
    expect(await screen.findByText("These filters apply to the totals, the curve and the legs below.")).toBeInTheDocument();
  });

  it("narrows the legs by the symbol of the best leg the totals name", async () => {
    renderWithQuery(<PayView />, {
      "/pnl/month": monthBody(),
      "/pnl/summary": summary({ best: leg({ candidate_id: "best-1", net_pnl: 149, outcome: "expired_worthless" }) }),
      "/pnl/equity": equity(),
      "/pnl/ledger": ledgerBody(),
    });
    fireEvent.click(await screen.findByRole("button", { name: /view nvda p 170\.00 in the ledger/i }));
    await waitFor(() => expect(calls()).toContain("/pnl/ledger?symbol=NVDA&book=all"));
    expect(screen.getByLabelText("Symbol")).toHaveValue("NVDA");
  });

  it("lists the legs as campaign threads that open to their legs", async () => {
    renderWithQuery(<PayView />, {
      "/pnl/month": monthBody(),
      "/pnl/summary": summary(),
      "/pnl/equity": equity(),
      "/pnl/ledger": ledgerBody([campaign({ legs: [leg(), leg({ candidate_id: "c2", strike: 175 })] })]),
    });
    const thread = await screen.findByRole("button", { name: /NVDA campaign/ });
    expect(thread).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("campaign-leg-count")).toHaveTextContent("2 legs");
    fireEvent.click(thread);
    expect(screen.getAllByTestId("leg-row")).toHaveLength(2);
  });

  it("says there are no trades for the filters, in words", async () => {
    serve();
    expect(await screen.findByText("No trades match the current filters.")).toBeInTheDocument();
  });

  it("says no marks are available rather than showing zeros", async () => {
    serve();
    expect(await screen.findByText("no marks available")).toBeInTheDocument();
  });

  it("draws the equity curve and says when it began", async () => {
    renderWithQuery(<PayView />, {
      "/pnl/month": monthBody(),
      "/pnl/summary": summary(),
      "/pnl/equity": {
        as_of: now(), filters,
        curve: {
          points: [{ entry_date: "2026-09-01", net_liquidation: 250000, unrealized_pnl: 100, cumulative_realized: 0, premium_cashflow: 42 }],
          gaps: [], starts_at: "2026-09-01",
        },
      },
      "/pnl/ledger": ledgerBody(),
    });
    expect(await screen.findByText(/since 1 September 2026/i)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /legend/i })).toBeInTheDocument();
  });

  it("says it could not load the curve and the legs, and that it tries again", async () => {
    renderWithQuery(<PayView />, { "/pnl/month": monthBody(), "/pnl/summary": summary() });
    expect(await screen.findByText("Could not load the equity curve.")).toBeInTheDocument();
    expect(await screen.findByText("Could not load the ledger.")).toBeInTheDocument();
    expect(screen.getAllByText("It tries again every 30 seconds.").length).toBeGreaterThanOrEqual(2);
  });

  it("keeps the page in one column that cannot outgrow the phone, so a wide table scrolls inside its card", async () => {
    const { container } = serve();
    await screen.findByRole("group", { name: /pay stub$/ });
    expect(container.firstElementChild).toHaveClass("grid-cols-1");
  });
  // The stepper's floor is the month the system began. The Legs filters belong to the cards under
  // the stepper, so a "Since" later than that start must not move it: the unfiltered curve answers
  // "/pnl/equity?book=all", and any filtered curve starts at its own (later) first journal row.
  const curveFrom = (startsAt: string) => ({
    as_of: now(), filters,
    curve: {
      points: [{ entry_date: startsAt, net_liquidation: 250000, unrealized_pnl: 100, cumulative_realized: 0, premium_cashflow: 42 }],
      gaps: [], starts_at: startsAt,
    },
  });
  const serveFilteredStart = () =>
    renderWithQuery(<PayView />, {
      "/pnl/month": monthBody(),
      "/pnl/summary": summary(),
      "/pnl/equity": curveFrom("2026-09-01"),
      "/pnl/equity?book=all": curveFrom("2026-06-24"),
      "/pnl/ledger": ledgerBody(),
    });
  // Wait until the filtered curve has landed (the curve card says it began on the filtered date),
  // so an assertion on the stepper cannot pass just because the new response is still on its way.
  const setSince = async (day: string) => {
    await screen.findByText(/since 24 June 2026/i);
    fireEvent.change(await screen.findByLabelText("Since"), { target: { value: day } });
    await screen.findByText(/since 1 September 2026/i);
  };

  it("keeps going back to the month the system began when the Legs filters start later", async () => {
    nav.params = new URLSearchParams("month=2026-07");
    serveFilteredStart();
    await screen.findByRole("heading", { name: "July 2026 pay" });
    await setSince("2026-09-01");
    expect(screen.getByRole("button", { name: "Previous month" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/activity?month=2026-06", { scroll: false });
  });

  it("stops at the month the system began, not at the filtered start, with a Since filter set", async () => {
    nav.params = new URLSearchParams("month=2026-06");
    serveFilteredStart();
    await screen.findByRole("heading", { name: "June 2026 pay" });
    await setSince("2026-09-01");
    expect(screen.getByRole("button", { name: "Previous month" })).toBeDisabled();
  });
});
