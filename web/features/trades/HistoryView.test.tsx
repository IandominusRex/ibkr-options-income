import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommandStatus } from "@/lib/commands";
import { apiFetchMock } from "@/lib/test-query";
import type { DayTrade } from "@/features/home/types";
import type { StrategyFilter } from "@/lib/strategy";
import { HistoryView, useInFlightCount } from "./HistoryView";

const DAY = "2026-10-15";

const approval = (over: Record<string, unknown> = {}) => ({
  as_of: "", id: 1, candidate_id: "c1", status: "pending", underlying: "AAPL",
  strategy: "cash_secured_put", right: "P", strike: 180, expiry: "2099-11-21", contracts: 1,
  premium: 2.35, blended_score: 0.7, created_at: "2026-10-15T15:00:00Z", expires_at: null,
  decided_at: null, order_state: null, source: "scan", review: null, rationale_tags: [], ...over,
});

const controls = {
  as_of: "", autonomy: { level: "full", label: "Full" }, rungs: [], halted: false, halt_reason: null,
  halted_at: null, mode: "paper", drain_healthy: true, drain_last_seen: null, pending_commands: 0,
};

const pending = {
  id: 7, kind: "approve", status: "pending", result: null, needs_confirmation: false,
  confirm_token: null, created_at: "", applied_at: null, as_of: "",
} as CommandStatus;

const order = (id: number, underlying: string, strategy: string, over: Record<string, unknown> = {}) => ({
  as_of: "x", id, candidate_id: `o${id}`, approval_id: null, underlying, strategy, strike: 190,
  expiry: null, state: "submitted", limit_price: 3.25, filled_qty: 0, avg_fill_price: null,
  is_live: false, detail: null, created_at: "2026-10-15T14:00:00Z", updated_at: "x", ...over,
});

const trade = (over: Partial<DayTrade> = {}): DayTrade => ({
  key: "c9:opened", action: "opened", how: null, kind: "csp", source: "wheel", underlying: "NVDA",
  right: "P", strike: 165, long_strike: null, expiry: "2099-11-21", contracts: 1,
  at: "2026-10-15T14:42:00Z", is_live: false, premium: 235, bought_back: null, commissions: 1.3,
  commissions_complete: true, net_pnl: null, capital: 16500, roc_pct: 1.4, annualized_pct: 13,
  pct_kept: null, dte_at_open: 39, days_held: null, reason: null, facts: [], approval_id: 9,
  review: null, rolled_to: null, decided_by: "system", ...over,
});

type World = {
  sent?: unknown[];
  range?: unknown[];
  orders?: unknown[];
  trades?: DayTrade[];
  previous?: string | null;
  next?: string | null;
  commandStatus?: string;
};

function serve(w: World = {}) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === "/options/approvals?status=pending") return { as_of: "", approvals: w.sent ?? [] };
    if (path.startsWith("/options/approvals?status=all")) return { as_of: "", approvals: w.range ?? [] };
    if (path === "/options/controls") return controls;
    if (path.startsWith("/options/orders")) return { as_of: "x", orders: w.orders ?? [] };
    if (path.startsWith("/pnl/day")) {
      return {
        as_of: "", date: DAY, book: "paper", strategy: "all", trades: w.trades ?? [], spreads_available: true,
        previous_day: w.previous ?? null, next_day: w.next ?? null,
      };
    }
    if (path.startsWith("/commands/")) return { ...pending, status: w.commandStatus ?? "pending" };
    throw new Error(`no mocked response for ${path}`);
  });
}

function mount(props: { strategy?: StrategyFilter; day?: string; submitted?: Map<number, CommandStatus> } = {}) {
  const onDay = vi.fn();
  const onSettled = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <HistoryView
        strategy={props.strategy ?? "all"}
        day={props.day ?? DAY}
        today={DAY}
        onDay={onDay}
        submitted={props.submitted ?? new Map()}
        onSettled={onSettled}
      />
    </QueryClientProvider>,
  );
  return { onDay, onSettled };
}

beforeEach(() => {
  (apiFetchMock as unknown as { mockClear: () => void }).mockClear();
  localStorage.clear();
});

describe("HistoryView", () => {
  it("shows today's in-flight work: a sent approval with its receipt, and working orders", async () => {
    serve({ sent: [approval()], orders: [order(4, "MSFT", "covered_call")] });
    mount({ submitted: new Map([[1, pending]]) });
    const flight = await screen.findByRole("region", { name: "In flight" });
    const card = await within(flight).findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(card).getByTestId("command-receipt")).toBeInTheDocument();
    const msft = (await within(flight).findByText("MSFT")).closest("li") as HTMLElement;
    expect(within(msft).getByText("Submitted")).toBeInTheDocument();
    expect(within(flight).getByText(/cancelled in IBKR/)).toBeInTheDocument();
  });

  it("a failed command hands the card back to Proposals", async () => {
    serve({ sent: [approval()], commandStatus: "failed" });
    const { onSettled } = mount({ submitted: new Map([[1, pending]]) });
    await waitFor(() => expect(onSettled).toHaveBeenCalledWith(1));
  });

  it("scopes working orders to the strategy; a roll order shows only under All", async () => {
    serve({ orders: [order(1, "NVDA", "cash_secured_put"), order(2, "MSFT", "covered_call"), order(3, "AMD", "roll")] });
    mount({ strategy: "csp" });
    const flight = await screen.findByRole("region", { name: "In flight" });
    expect(await within(flight).findByText("NVDA")).toBeInTheDocument();
    expect(within(flight).queryByText("MSFT")).toBeNull();
    expect(within(flight).queryByText("AMD")).toBeNull();
  });

  it("leaves out In flight on a past day, and when nothing is in flight", async () => {
    serve({ orders: [order(1, "NVDA", "cash_secured_put")], trades: [trade()] });
    mount({ day: "2026-10-09" });
    await screen.findByRole("article", { name: "NVDA · Sold $165 put" });
    expect(screen.queryByRole("region", { name: "In flight" })).toBeNull();
  });

  it("lists the day's trades as Home's cards, saying who approved them", async () => {
    serve({ trades: [trade()] });
    mount();
    const traded = await screen.findByRole("region", { name: "Traded" });
    const card = await within(traded).findByRole("article", { name: "NVDA · Sold $165 put" });
    expect(within(card).getByText("Approved by the system")).toBeInTheDocument();
  });

  it("leaves credit spreads to the Credit spreads switcher", async () => {
    serve({ trades: [trade(), trade({ key: "s1:opened", source: "spreads", kind: "spread", underlying: "SPY", long_strike: 757, strike: 762 })] });
    mount();
    const traded = await screen.findByRole("region", { name: "Traded" });
    await within(traded).findByRole("article", { name: "NVDA · Sold $165 put" });
    expect(within(traded).getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("link", { name: /Credit spreads/ })).toHaveAttribute("href", "/trades?strategy=spread");
  });

  it("says so when nothing traded", async () => {
    serve();
    mount({ day: "2026-10-09" });
    expect(await screen.findByText("Nothing traded on Fri, Oct 9.")).toBeInTheDocument();
  });

  it("lists proposals that did not trade, with the outcome and who decided, each opening its page", async () => {
    serve({
      range: [
        approval({ id: 3, status: "approved", order_state: "cancelled", decided_by: "system", underlying: "TSLA", strike: 260 }),
        approval({ id: 4, status: "expired", underlying: "KO", strike: 60, created_at: "2026-10-15T14:00:00Z" }),
      ],
    });
    mount();
    const not = await screen.findByRole("region", { name: "Not traded" });
    const tsla = await within(not).findByRole("link", { name: /TSLA/ });
    expect(tsla).toHaveAttribute("href", "/trades/3");
    expect(within(tsla).getByText("Order cancelled")).toBeInTheDocument();
    expect(within(tsla).getByText(/Approved by the system/)).toBeInTheDocument();
    expect(within(not).getByRole("link", { name: /KO/ })).toHaveTextContent(/Expired unanswered/);
  });

  it("an approval decided before the record existed says only Approved", async () => {
    serve({ range: [approval({ id: 3, status: "approved", order_state: "rejected" })] });
    mount();
    const row = await screen.findByRole("link", { name: /AAPL/ });
    expect(row).toHaveTextContent(/Approved · raised/);
    expect(row).not.toHaveTextContent(/by the system|by you/);
  });

  it("asks for the day either side and keeps the New York day", async () => {
    serve({ range: [approval({ id: 3, status: "expired", created_at: "2026-10-15T03:00:00Z" })] });
    mount();
    await screen.findByRole("region", { name: "Traded" });
    expect(apiFetchMock.mock.calls.some((c) => c[0] === "/options/approvals?status=all&since=2026-10-14&until=2026-10-16&limit=200")).toBe(true);
    // 03:00 UTC on the 15th is the 14th in New York.
    expect(screen.queryByRole("region", { name: "Not traded" })).toBeNull();
  });

  it("steps to the neighbouring days with trades, and back to today", async () => {
    serve({ previous: "2026-10-09", next: null });
    const { onDay } = mount({ day: "2026-10-12" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Previous day with trades" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Previous day with trades" }));
    expect(onDay).toHaveBeenCalledWith("2026-10-09");
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(onDay).toHaveBeenCalledWith(null);
    // No later day has trades, so next goes back to today.
    onDay.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Back to today" }));
    expect(onDay).toHaveBeenCalledWith(null);
  });

  it("keeps Today left of the arrows, and next goes to the following day with trades", async () => {
    serve({ previous: "2026-10-09", next: "2026-10-13" });
    const { onDay } = mount({ day: "2026-10-12" });
    const next = await screen.findByRole("button", { name: "Next day with trades" });
    const names = screen.getAllByRole("button").map((b) => b.textContent || b.getAttribute("aria-label"));
    expect(names.indexOf("Today")).toBeLessThan(names.indexOf("Previous day with trades"));
    fireEvent.click(next);
    expect(onDay).toHaveBeenCalledWith("2026-10-13");
  });

  it("counts what is in flight: sent approvals plus working orders in scope", async () => {
    serve({ sent: [approval()], orders: [order(1, "NVDA", "cash_secured_put"), order(2, "MSFT", "covered_call")] });
    function Count() {
      const n = useInFlightCount("all", new Map([[1, pending]]));
      return <p>count {n === null ? "unknown" : n}</p>;
    }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <Count />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("count 3")).toBeInTheDocument();
  });
});
