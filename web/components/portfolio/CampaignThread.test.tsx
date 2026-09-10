import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { CampaignThread } from "./CampaignThread";
import { CampaignsPanel } from "./CampaignsPanel";
import type { CampaignLeg, CampaignSummary } from "./types";

// Task 3.4 — both components' tests live here, per the task brief's Files
// line naming only CampaignThread.test.tsx despite two components (and
// CampaignsPanel being the query-driving one) being built. Mirrors how
// Task 3.3 put PositionsPanel-level tests in PositionGroup.test.tsx.

const ISO = new Date().toISOString();

function aLeg(overrides: Partial<CampaignLeg> = {}): CampaignLeg {
  return {
    as_of: ISO,
    candidate_id: "cand-1",
    strategy: "csp",
    right: "P",
    strike: 220,
    expiry: "2026-01-16",
    known: true,
    ...overrides,
  };
}

function aCampaign(overrides: Partial<CampaignSummary> = {}): CampaignSummary {
  return {
    as_of: ISO,
    campaign_id: "camp-1",
    symbol: "AAPL",
    status: "open",
    opened_date: "2026-01-01",
    closed_date: null,
    legs: [aLeg()],
    total_premium_collected: 500,
    total_debit_paid: 0,
    net_premium: 500,
    assigned: false,
    adjusted_cost_basis: null,
    realized_stock_pnl: null,
    ...overrides,
  };
}

describe("CampaignThread", () => {
  it("renders symbol, status, net premium and leg count collapsed", () => {
    render(
      <CampaignThread
        campaign={aCampaign({
          symbol: "AAPL",
          status: "open",
          net_premium: 500,
          legs: [aLeg(), aLeg({ candidate_id: "cand-2" })],
        })}
      />,
    );

    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("campaign-status")).toHaveTextContent(/open/i);
    expect(screen.getByText("+$500.00")).toBeInTheDocument();
    expect(screen.getByTestId("campaign-leg-count")).toHaveTextContent("2 legs");
    // Collapsed by default - the legs list itself is not in the document yet.
    expect(screen.queryByTestId("campaign-legs")).toBeNull();
  });

  it("clicking expands to the legs in order; clicking again collapses", () => {
    const legA = aLeg({ candidate_id: "cand-a", strike: 100 });
    const legB = aLeg({ candidate_id: "cand-b", strike: 200 });
    render(<CampaignThread campaign={aCampaign({ legs: [legA, legB] })} />);

    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const legs = screen.getAllByTestId("campaign-leg");
    expect(legs).toHaveLength(2);
    expect(legs[0]).toHaveTextContent("100.00");
    expect(legs[1]).toHaveTextContent("200.00");

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("campaign-legs")).toBeNull();
  });

  it("expanding one campaign's legs does not expand another's", () => {
    render(
      <>
        <CampaignThread campaign={aCampaign({ campaign_id: "camp-1", symbol: "AAPL" })} />
        <CampaignThread campaign={aCampaign({ campaign_id: "camp-2", symbol: "MSFT" })} />
      </>,
    );

    const [firstButton, secondButton] = screen.getAllByRole("button");
    fireEvent.click(firstButton);

    expect(firstButton).toHaveAttribute("aria-expanded", "true");
    expect(secondButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.getAllByTestId("campaign-legs")).toHaveLength(1);
  });

  it("renders a known:false leg as unavailable with its candidate_id, not omitted, and the collapsed leg count still matches", () => {
    const legs = [
      aLeg({ candidate_id: "cand-known", known: true }),
      aLeg({
        candidate_id: "cand-missing",
        known: false,
        right: null,
        strike: null,
        expiry: null,
      }),
    ];
    render(<CampaignThread campaign={aCampaign({ legs })} />);

    expect(screen.getByTestId("campaign-leg-count")).toHaveTextContent("2 legs");

    fireEvent.click(screen.getByRole("button"));
    const legRows = screen.getAllByTestId("campaign-leg");
    expect(legRows).toHaveLength(2);
    expect(screen.getByText(/leg unavailable/i)).toBeInTheDocument();
    expect(screen.getByText("cand-missing")).toBeInTheDocument();
  });

  it("renders adjusted cost basis and realized stock P&L for an assigned campaign", () => {
    render(
      <CampaignThread
        campaign={aCampaign({ assigned: true, adjusted_cost_basis: 175, realized_stock_pnl: 320 })}
      />,
    );

    expect(screen.getByTestId("campaign-adjusted-basis")).toHaveTextContent("$175.00");
    expect(screen.getByTestId("campaign-realized-pnl")).toHaveTextContent("$320.00");
  });

  it("renders neither the adjusted cost basis nor realized stock P&L row for a non-assigned campaign", () => {
    render(<CampaignThread campaign={aCampaign({ assigned: false })} />);

    expect(screen.queryByTestId("campaign-adjusted-basis")).toBeNull();
    expect(screen.queryByTestId("campaign-realized-pnl")).toBeNull();
  });

  it("renders n/a, not $0, when an assigned campaign has realized_stock_pnl: null", () => {
    render(
      <CampaignThread
        campaign={aCampaign({ assigned: true, adjusted_cost_basis: 175, realized_stock_pnl: null })}
      />,
    );

    const el = screen.getByTestId("campaign-realized-pnl");
    expect(el).toHaveTextContent(/n\/a/i);
    expect(el).not.toHaveTextContent("$0");
  });

  it("I5: marks net premium, adjusted cost basis and realized stock P&L as gross of commissions", () => {
    // GET /portfolio/campaigns documents these three figures as gross
    // (src/api/routers/portfolio.py:296-299) - Money's `complete` prop defaults
    // to true, an affirmative "net" claim, so all three must pass
    // complete={false} to surface the qualifier rather than misstate the gap.
    render(
      <CampaignThread
        campaign={aCampaign({
          net_premium: 500,
          assigned: true,
          adjusted_cost_basis: 175,
          realized_stock_pnl: 320,
        })}
      />,
    );

    // net_premium sits in the collapsed header, outside any testid wrapper -
    // assert against the whole rendered thread.
    expect(screen.getByTestId("campaign-thread")).toHaveTextContent(/gross/i);
    expect(screen.getByTestId("campaign-adjusted-basis")).toHaveTextContent(/gross/i);
    expect(screen.getByTestId("campaign-realized-pnl")).toHaveTextContent(/gross/i);
  });
});

describe("CampaignsPanel", () => {
  it("renders one line of text and no icon circle when there are no campaigns", async () => {
    renderWithQuery(<CampaignsPanel />, {
      "/portfolio/campaigns": { as_of: ISO, campaigns: [] },
    });

    expect(await screen.findByText(/no campaigns/i)).toBeInTheDocument();
    expect(document.querySelector("svg")).toBeNull();
  });

  it("renders one CampaignThread per campaign in the response", async () => {
    renderWithQuery(<CampaignsPanel />, {
      "/portfolio/campaigns": {
        as_of: ISO,
        campaigns: [
          aCampaign({ campaign_id: "camp-1", symbol: "AAPL" }),
          aCampaign({ campaign_id: "camp-2", symbol: "MSFT" }),
        ],
      },
    });

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
  });

  it("changing the status filter refetches with the new query string, not a client-side filter", async () => {
    renderWithQuery(<CampaignsPanel />, {
      "/portfolio/campaigns": { as_of: ISO, campaigns: [aCampaign()] },
    });
    await screen.findByText("AAPL");
    const callsBefore = apiFetchMock.mock.calls.length;

    fireEvent.change(screen.getByLabelText(/status/i), { target: { value: "open" } });

    await waitFor(() => {
      expect(apiFetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
    const lastCall = apiFetchMock.mock.calls.at(-1)?.[0];
    expect(lastCall).toContain("/portfolio/campaigns");
    expect(lastCall).toContain("status=open");
  });

  it("changing the symbol filter refetches with the new (upper-cased) query string", async () => {
    renderWithQuery(<CampaignsPanel />, {
      "/portfolio/campaigns": { as_of: ISO, campaigns: [aCampaign()] },
    });
    await screen.findByText("AAPL");
    const callsBefore = apiFetchMock.mock.calls.length;

    fireEvent.change(screen.getByLabelText(/symbol/i), { target: { value: "aapl" } });

    await waitFor(() => {
      expect(apiFetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
    const lastCall = apiFetchMock.mock.calls.at(-1)?.[0];
    expect(lastCall).toContain("symbol=AAPL");
  });
});
