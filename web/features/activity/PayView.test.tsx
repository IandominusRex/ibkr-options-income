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
const serve = (month: unknown = monthBody(), eq: unknown = equity()) =>
  renderWithQuery(<PayView />, {
    "/pnl/month": month,
    "/pnl/summary": summary(),
    "/pnl/equity": eq,
    "/pnl/ledger": { as_of: now(), filters, campaigns: [], marks_as_of: null, n_legs: 0 },
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
});
