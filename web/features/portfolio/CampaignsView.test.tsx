import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { CampaignsView } from "./CampaignsView";

const leg = (id: string, over: Record<string, unknown> = {}) => ({
  as_of: "", candidate_id: id, strategy: "cash_secured_put", right: "P", strike: 180,
  expiry: "2026-11-20", known: true, ...over,
});
const campaign = (over: Record<string, unknown> = {}) => ({
  as_of: "", campaign_id: "c1", symbol: "NVDA", status: "open", opened_date: "2026-10-01",
  closed_date: null, legs: [leg("a"), leg("b")], total_premium_collected: 600, total_debit_paid: 0,
  net_premium: 600, assigned: false, adjusted_cost_basis: null, realized_stock_pnl: null, ...over,
});
const serve = (campaigns: unknown[]) =>
  renderWithQuery(<CampaignsView />, { "/portfolio/campaigns": { as_of: "", campaigns } });
const campaignCalls = () => apiFetchMock.mock.calls.map((c) => c[0]).filter((p) => String(p).startsWith("/portfolio/campaigns"));

describe("CampaignsView", () => {
  it("shows a thread with its status, its dates and its net premium, said to be before commissions", async () => {
    serve([campaign()]);
    expect(await screen.findByRole("heading", { name: "NVDA" })).toBeInTheDocument();
    const card = screen.getByRole("article");
    // "Open" is also a chip above the list, so the status word is read inside the card.
    expect(within(card).getByText("Open")).toBeInTheDocument();
    expect(within(card).getByText("Opened Oct 1, 2026 · 2 legs")).toBeInTheDocument();
    expect(within(card).getByText("+$600.00")).toBeInTheDocument();
    expect(within(card).getByText("net premium, before commissions")).toBeInTheDocument();
  });

  it("gives a closed thread's span and writes a loss with a real minus", async () => {
    serve([campaign({ status: "closed", closed_date: "2026-10-20", net_premium: -120 })]);
    const card = (await screen.findByRole("heading", { name: "NVDA" })).closest("article") as HTMLElement;
    expect(within(card).getByText("Oct 1, 2026 to Oct 20, 2026 · 2 legs")).toBeInTheDocument();
    expect(within(card).getByText("Closed")).toBeInTheDocument();
    expect(within(card).getByText("−$120.00")).toBeInTheDocument();
  });

  it("shows an assigned thread's adjusted cost basis and realised stock P&L, and an unassigned one's neither", async () => {
    serve([
      campaign({ assigned: true, adjusted_cost_basis: 172.4, realized_stock_pnl: 250 }),
      campaign({ campaign_id: "c2", symbol: "AMD" }),
    ]);
    const group = await screen.findByRole("group", { name: "NVDA assigned shares" });
    expect(within(group).getByText("$172.40")).toBeInTheDocument();
    expect(within(group).getByText("+$250.00")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "AMD assigned shares" })).toBeNull();
  });

  it("renders an unknown basis as a hatched n/a, never $0", async () => {
    serve([campaign({ assigned: true, adjusted_cost_basis: null, realized_stock_pnl: null })]);
    const group = await screen.findByRole("group", { name: "NVDA assigned shares" });
    const na = within(group).getAllByText("n/a");
    expect(na).toHaveLength(2);
    expect(na[0].closest("dd")).toHaveClass("hatch");
    expect(screen.queryByText("$0")).toBeNull();
  });

  it("keeps the legs behind a disclosure, and says when a leg's record was pruned", async () => {
    serve([campaign({ legs: [leg("a"), leg("b", { known: false, right: null, strike: null, expiry: null })] })]);
    const known = await screen.findByText("CSP $180 put");
    expect(known).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /2 legs/ }));
    expect(known).toBeVisible();
    expect(screen.getByText("Leg unavailable")).toBeVisible();
    expect(screen.getByText("b")).toBeInTheDocument();
  });

  it("asks the API for the chosen status and symbol, not a client-side filter", async () => {
    serve([campaign()]);
    await screen.findByRole("heading", { name: "NVDA" });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    await waitFor(() => expect(campaignCalls()).toContain("/portfolio/campaigns?status=open"));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "nvda" } });
    await waitFor(() => expect(campaignCalls()).toContain("/portfolio/campaigns?status=open&symbol=NVDA"));
    expect(campaignCalls()).toContain("/portfolio/campaigns");
  });

  it("says nothing matches the filters, in words", async () => {
    serve([]);
    expect(await screen.findByText("No campaigns match the current filters.")).toBeInTheDocument();
  });

  it("says it could not load, and that it tries again", async () => {
    renderWithQuery(<CampaignsView />, {});
    expect(await screen.findByText("Could not load campaigns.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every 30 seconds.")).toBeInTheDocument();
  });
});
