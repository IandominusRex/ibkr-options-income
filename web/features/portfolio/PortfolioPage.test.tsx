import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
// test-query registers the @/lib/api mock when it is evaluated, so it must load before anything
// that imports @/lib/api (RefreshControl does through lib/commands).
import { apiFetchMock } from "@/lib/test-query";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/portfolio",
}));

import { PortfolioPage } from "./PortfolioPage";

const now = () => new Date().toISOString();
const sourced = (value: number) => ({ value, source: "ibkr", as_of: now(), stale: false });

function serve() {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === "/portfolio/summary") {
      return {
        as_of: now(), source: "monitor", degraded: false, note: null,
        account: {
          as_of: now(), net_liquidation: sourced(125_000), total_cash: sourced(1), buying_power: sourced(1),
          maintenance_margin: sourced(1), excess_liquidity: sourced(1),
        },
        exposure: {
          as_of: now(), open_positions: 1, open_shorts: 1, open_campaigns: 1, net_delta_exposure: 0,
          cash_secured_against_puts: 0, buying_power_utilisation_pct: 1, shorts_at_assignment_risk: 0,
        },
      };
    }
    if (path === "/portfolio/positions") return { as_of: now(), source: "monitor", degraded: false, groups: [] };
    if (path.startsWith("/spreads/positions")) return { as_of: "", available: true, underlying: "SPY", mode: "paper", positions: [] };
    if (path === "/options/shorts") return { as_of: "", shorts: [] };
    if (path === "/claude/context") return { available: false, dossiers: [] };
    if (path.startsWith("/portfolio/campaigns")) return { as_of: "", campaigns: [] };
    if (path.startsWith("/portfolio/calendar")) {
      return { as_of: now(), source: "monitor", degraded: false, horizon_days: 45, days: [] };
    }
    if (path === "/options/controls") {
      return { as_of: "", autonomy: { level: "full", label: "Full" }, rungs: [], halted: false, mode: "paper", drain_healthy: true, drain_last_seen: null, pending_commands: 0 };
    }
    throw new Error(`no mocked response for ${path}`);
  });
}

const summaryCalls = () => apiFetchMock.mock.calls.filter((c) => c[0] === "/portfolio/summary").length;
const tree = (qc: QueryClient) => (
  <QueryClientProvider client={qc}>
    <PortfolioPage />
  </QueryClientProvider>
);
const mount = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const r = render(tree(qc));
  return { rerenderPage: () => r.rerender(tree(qc)) };
};

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
  serve();
});

describe("PortfolioPage", () => {
  it("opens on Positions with the three view chips, the Account card above them and Refresh in the header", async () => {
    mount();
    expect(screen.getByRole("heading", { level: 1, name: "Portfolio" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(await screen.findByText("No open positions.")).toBeInTheDocument();
    const views = screen.getByRole("group", { name: "View" });
    expect(within(views).getByRole("button", { name: "Positions" })).toHaveAttribute("aria-pressed", "true");
    expect(within(views).getByRole("button", { name: "Campaigns" })).toHaveAttribute("aria-pressed", "false");
    expect(within(views).getByRole("button", { name: "Calendar" })).toHaveAttribute("aria-pressed", "false");
    expect(await screen.findByTestId("account-donut")).toHaveTextContent("$125,000.00");
  });

  it("opens the view the URL asks for, and Positions for one it does not know", async () => {
    nav.params = new URLSearchParams("view=campaigns");
    const page = mount();
    expect(await screen.findByText("No campaigns match the current filters.")).toBeInTheDocument();
    nav.params = new URLSearchParams("view=bogus");
    page.rerenderPage();
    expect(await screen.findByText("No open positions.")).toBeInTheDocument();
  });

  it("writes the chosen view into the URL", async () => {
    mount();
    await screen.findByText("No open positions.");
    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(nav.replace).toHaveBeenCalledWith("/portfolio?view=calendar", { scroll: false });
  });

  it("changing the view does not fetch the account summary again", async () => {
    // The mock's call log spans the whole file, so count from where this test starts.
    const before = summaryCalls();
    const page = mount();
    await screen.findByTestId("account-donut");
    expect(summaryCalls() - before).toBe(1);
    nav.params = new URLSearchParams("view=calendar");
    page.rerenderPage();
    expect(await screen.findByText("No option expiries within the next 45 days.")).toBeInTheDocument();
    expect(summaryCalls() - before).toBe(1);
  });
});
