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
  it("puts net liquidation at the centre of a donut whose rings are buying power used and cash left", async () => {
    serve(reading());
    const donut = await screen.findByTestId("account-donut");
    expect(within(donut).getByText("Net liquidation")).toBeInTheDocument();
    expect(within(donut).getByText("$125,000")).toBeInTheDocument();
    expect(within(donut).getByText(".00")).toBeInTheDocument();
    expect(within(donut).getByRole("img")).toHaveAccessibleName(
      "Net liquidation $125,000.00. Buying power used 22.5%. Cash 32.0% of the account.",
    );
    // Each ring's percent and the sum behind it are written out, not left to the arc.
    expect(screen.getByText("Buying power used")).toBeInTheDocument();
    expect(screen.getByText("22.5%")).toBeInTheDocument();
    expect(screen.getByText("$18,000.00 secured against puts, of $80,000.00 buying power")).toBeInTheDocument();
    expect(screen.getByText("Cash left")).toBeInTheDocument();
    expect(screen.getByText("32.0%")).toBeInTheDocument();
    expect(screen.getByText("$40,000.00 of $125,000.00 net liquidation")).toBeInTheDocument();
  });

  it("lists the rest as figure lines, with no Delayed word on a live reading", async () => {
    serve(reading());
    const risk = await screen.findByRole("group", { name: "Margin and risk figures" });
    expect(within(risk).getByText("Maintenance margin")).toBeInTheDocument();
    expect(within(risk).getByText("$12,000.00")).toBeInTheDocument();
    expect(within(risk).getByText("Excess liquidity")).toBeInTheDocument();
    expect(within(risk).getByText("Shorts at assignment risk")).toBeInTheDocument();
    expect(within(risk).getByText("−150")).toBeInTheDocument(); // a real minus, not a hyphen
    const book = screen.getByRole("group", { name: "Book figures" });
    expect(within(book).getByText("Open shorts")).toBeInTheDocument();
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
    expect(screen.queryByTestId("account-donut")).toBeNull();
    expect(screen.queryByRole("group", { name: "Margin and risk figures" })).toBeNull();
    expect(screen.queryByText("Delayed")).toBeNull();
  });

  it("uses the API's own words for the empty rung when it has some", async () => {
    serve(reading({ source: "none", degraded: true, account: null, exposure: null, note: "The monitor has not run yet." }));
    expect(await screen.findByText("The monitor has not run yet.")).toBeInTheDocument();
  });

  it("renders a figure we do not have as a hatched n/a, never $0", async () => {
    serve(reading({ account: account({ net_liquidation: sourced(null), maintenance_margin: sourced(null) }) }));
    const donut = await screen.findByTestId("account-donut");
    expect(within(donut).getByText("n/a")).toHaveClass("hatch");
    const risk = screen.getByRole("group", { name: "Margin and risk figures" });
    expect(within(risk).getByText("n/a").closest("dd")).toHaveClass("hatch");
    expect(screen.queryByText("$0")).toBeNull();
    // Cash cannot be a share of an account we cannot value: n/a, not 0%.
    expect(screen.queryByText("0.0%")).toBeNull();
  });

  it("says a stale figure is stale, in words", async () => {
    serve(reading({ account: account({ maintenance_margin: sourced(12_000, true), net_liquidation: sourced(125_000, true) }) }));
    const risk = await screen.findByRole("group", { name: "Margin and risk figures" });
    expect(within(risk).getByText("stale")).toBeInTheDocument();
    expect(screen.getByText("Net liquidation · stale")).toBeInTheDocument();
  });

  it("renders an unknown buying-power use as n/a, not 0%", async () => {
    serve(reading({ exposure: exposure({ buying_power_utilisation_pct: null }) }));
    const donut = await screen.findByTestId("account-donut");
    expect(donut).not.toHaveTextContent("0.0%");
    expect(screen.queryByText("0.0%")).toBeNull();
    expect(screen.getAllByText("n/a").length).toBeGreaterThan(0);
  });

  it("says it could not load, and that it tries again, when the request fails", async () => {
    renderWithQuery(<SummaryCard />, {});
    expect(await screen.findByText("Could not load the account summary.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every 30 seconds.")).toBeInTheDocument();
  });
});
