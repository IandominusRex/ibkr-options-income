import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SummaryPanel } from "./SummaryPanel";

function sourced(value: number | null, stale = false) {
  return { value, source: "ibkr" as const, as_of: new Date().toISOString(), stale };
}

function anAccount(overrides: Record<string, unknown> = {}) {
  return {
    as_of: new Date().toISOString(),
    net_liquidation: sourced(125_000),
    total_cash: sourced(40_000),
    buying_power: sourced(80_000),
    maintenance_margin: sourced(12_000),
    excess_liquidity: sourced(68_000),
    ...overrides,
  };
}

function anExposure(overrides: Record<string, unknown> = {}) {
  return {
    as_of: new Date().toISOString(),
    open_positions: 6,
    open_shorts: 3,
    open_campaigns: 2,
    net_delta_exposure: -150,
    cash_secured_against_puts: 18_000,
    buying_power_utilisation_pct: 22.5,
    shorts_at_assignment_risk: 1,
    ...overrides,
  };
}

describe("SummaryPanel", () => {
  it("renders the five account values through Money", async () => {
    const { container } = renderWithQuery(<SummaryPanel />, {
      "/portfolio/summary": {
        source: "monitor",
        degraded: false,
        account: anAccount(),
        exposure: anExposure(),
        note: null,
        as_of: new Date().toISOString(),
      },
    });
    // Net liquidation is 125,000 - formatMoneyCell renders full precision with
    // comma grouping and cents (lib/money.ts), distinct from formatMoney's
    // compact dashboard notation.
    await screen.findByText("$125,000.00");
    expect(container.querySelectorAll('[data-kind="value"]').length).toBeGreaterThanOrEqual(5);
  });

  it("renders the empty state and no figures when nothing has been captured", async () => {
    renderWithQuery(<SummaryPanel />, {
      "/portfolio/summary": {
        source: "none",
        degraded: true,
        account: null,
        exposure: null,
        note: "No portfolio snapshot has been captured yet.",
        as_of: new Date().toISOString(),
      },
    });
    expect(await screen.findByText(/no portfolio snapshot/i)).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).toBeNull();
  });

  it("renders the backend's own note for a degraded reading", async () => {
    renderWithQuery(<SummaryPanel />, {
      "/portfolio/summary": {
        source: "eod",
        degraded: true,
        note: "Values are from the last end-of-day run.",
        account: anAccount(),
        exposure: anExposure(),
        as_of: new Date().toISOString(),
      },
    });
    expect(await screen.findByText(/last end-of-day run/i)).toBeInTheDocument();
  });

  it("renders unknown utilisation as n/a, not as zero percent", async () => {
    renderWithQuery(<SummaryPanel />, {
      "/portfolio/summary": {
        source: "monitor",
        degraded: false,
        account: anAccount(),
        exposure: { ...anExposure(), buying_power_utilisation_pct: null },
        note: null,
        as_of: new Date().toISOString(),
      },
    });
    await screen.findByText("$125,000.00");
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.getAllByText(/n\/a/i).length).toBeGreaterThan(0);
  });

  it("renders the stale wording for an old reading", async () => {
    const old = new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString();
    renderWithQuery(<SummaryPanel />, {
      "/portfolio/summary": {
        source: "monitor",
        degraded: false,
        account: anAccount(),
        exposure: anExposure(),
        note: null,
        as_of: old,
      },
    });
    expect(await screen.findByText(/stale/i)).toBeInTheDocument();
  });

  it("puts the freshness label at the top, driven by the response's own as_of", async () => {
    const when = new Date(Date.now() - 12 * 60 * 1000).toISOString();
    renderWithQuery(<SummaryPanel />, {
      "/portfolio/summary": {
        source: "monitor",
        degraded: false,
        account: anAccount(),
        exposure: anExposure(),
        note: null,
        as_of: when,
      },
    });
    expect(await screen.findByText(/12m ago/)).toBeInTheDocument();
  });

  it("does not render a DegradedNotice for the empty (none) rung - the empty state covers it", async () => {
    renderWithQuery(<SummaryPanel />, {
      "/portfolio/summary": {
        source: "none",
        degraded: true,
        account: null,
        exposure: null,
        note: "No portfolio snapshot has been captured yet.",
        as_of: new Date().toISOString(),
      },
    });
    await screen.findByText(/no portfolio snapshot/i);
    expect(screen.queryByTestId("degraded-notice")).toBeNull();
  });

  it("marks an individually stale account field with the word stale, not colour alone", async () => {
    renderWithQuery(<SummaryPanel />, {
      "/portfolio/summary": {
        source: "monitor",
        degraded: false,
        account: anAccount({ net_liquidation: sourced(125_000, true) }),
        exposure: anExposure(),
        note: null,
        as_of: new Date().toISOString(),
      },
    });
    await screen.findByText("$125,000.00");
    expect(screen.getAllByText("stale").length).toBeGreaterThan(0);
  });
});
