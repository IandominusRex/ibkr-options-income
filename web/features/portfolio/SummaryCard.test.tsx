import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SummaryCard } from "./SummaryCard";

const now = () => new Date().toISOString();
const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const sourced = (value: number | null, stale = false) => ({ value, source: "ibkr", as_of: now(), stale });
const account = (over: Record<string, unknown> = {}) => ({
  as_of: now(),
  net_liquidation: sourced(125_000),
  total_cash: sourced(40_000),
  buying_power: sourced(80_000),
  maintenance_margin: sourced(12_000),
  excess_liquidity: sourced(68_000),
  ...over,
});
const exposure = (over: Record<string, unknown> = {}) => ({
  as_of: now(),
  open_positions: 6,
  open_shorts: 3,
  open_campaigns: 2,
  net_delta_exposure: -150,
  cash_secured_against_puts: 18_000,
  buying_power_utilisation_pct: 22.5,
  shorts_at_assignment_risk: 1,
  ...over,
});
const reading = (over: Record<string, unknown> = {}) => ({
  as_of: now(),
  source: "monitor",
  degraded: false,
  account: account(),
  exposure: exposure(),
  note: null,
  ...over,
});
const serve = (body: unknown) => renderWithQuery(<SummaryCard />, { "/portfolio/summary": body });

describe("SummaryCard", () => {
  it("shows the account and the exposure as figure lines, with no Delayed word on a live reading", async () => {
    serve(reading());
    const acct = await screen.findByRole("group", { name: "Account figures" });
    expect(within(acct).getByText("Net liquidation")).toBeInTheDocument();
    expect(within(acct).getByText("$125,000.00")).toBeInTheDocument();
    const expo = screen.getByRole("group", { name: "Exposure figures" });
    expect(within(expo).getByText("Open shorts")).toBeInTheDocument();
    expect(within(expo).getByText("Shorts at assignment risk")).toBeInTheDocument();
    expect(within(expo).getByText("−150")).toBeInTheDocument(); // a real minus, not a hyphen
    expect(within(expo).getByText("22.5%")).toBeInTheDocument();
    expect(screen.queryByText("Delayed")).toBeNull();
  });

  it("says Delayed, the age and the API's note verbatim when the reading is degraded and old", async () => {
    serve(reading({ source: "eod", degraded: true, as_of: ago(3), note: "Values are from the last end-of-day run." }));
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
    expect(screen.getByTestId("degraded-notice")).toHaveTextContent("Values are from the last end-of-day run.");
  });

  it("says Delayed for an old reading even when nothing marks it degraded, and adds no notice", async () => {
    serve(reading({ as_of: ago(2) }));
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.queryByTestId("degraded-notice")).toBeNull();
  });

  it("says why there is nothing when no snapshot has been captured, and shows no figures", async () => {
    serve(reading({ source: "none", degraded: true, account: null, exposure: null, note: null }));
    expect(await screen.findByText("No portfolio snapshot has been captured yet.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Account figures" })).toBeNull();
    expect(screen.queryByText("Delayed")).toBeNull();
  });

  it("uses the API's own words for the empty rung when it has some", async () => {
    serve(reading({ source: "none", degraded: true, account: null, exposure: null, note: "The monitor has not run yet." }));
    expect(await screen.findByText("The monitor has not run yet.")).toBeInTheDocument();
  });

  it("renders a figure we do not have as a hatched n/a, never $0", async () => {
    serve(reading({ account: account({ net_liquidation: sourced(null) }) }));
    const acct = await screen.findByRole("group", { name: "Account figures" });
    const na = within(acct).getAllByText("n/a")[0];
    expect(na.closest("dd")).toHaveClass("hatch");
    expect(screen.queryByText("$0")).toBeNull();
  });

  it("says a stale figure is stale, in words", async () => {
    serve(reading({ account: account({ buying_power: sourced(80_000, true) }) }));
    const acct = await screen.findByRole("group", { name: "Account figures" });
    expect(within(acct).getByText("stale")).toBeInTheDocument();
  });

  it("renders an unknown buying-power use as n/a, not 0%", async () => {
    serve(reading({ exposure: exposure({ buying_power_utilisation_pct: null }) }));
    const expo = await screen.findByRole("group", { name: "Exposure figures" });
    expect(within(expo).queryByText("0.0%")).toBeNull();
    expect(within(expo).getByText("n/a")).toBeInTheDocument();
  });

  it("says it could not load, and that it tries again, when the request fails", async () => {
    renderWithQuery(<SummaryCard />, {});
    expect(await screen.findByText("Could not load the account summary.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every 30 seconds.")).toBeInTheDocument();
  });
});
