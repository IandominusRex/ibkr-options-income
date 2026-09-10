import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CampaignRow } from "./CampaignRow";
import { LedgerFilters } from "./LedgerFilters";
import { LegRow } from "./LegRow";
import { LedgerTable } from "./LedgerTable";
import type { CampaignPnlData, LedgerResponseData, PnlLegData } from "./types";

// Task 5.4 — the ledger table. Both components' tests live here per the task
// brief's Files line (LedgerTable.test.tsx despite the five components), the
// same convention CampaignThread.test.tsx set in M3 Task 3.4.

const ISO = new Date().toISOString();

function aLeg(overrides: Partial<PnlLegData> = {}): PnlLegData {
  return {
    candidate_id: "cand-1",
    campaign_id: null,
    symbol: "NVDA 261016 00170000P",
    underlying: "NVDA",
    strategy: "cash_secured_put",
    right: "P",
    strike: 170,
    expiry: "2026-10-16",
    contracts: 1,
    opened_at: ISO,
    closed_at: null,
    credit: 150,
    debit: 0,
    commissions: 1,
    commissions_complete: true,
    net_pnl: null,
    unrealized_pnl: null,
    days_held: 5,
    roc_pct: 0.88,
    annualized_pct: null,
    outcome: "still_open",
    is_live: false,
    ...overrides,
  };
}

function aCampaign(overrides: Partial<CampaignPnlData> = {}): CampaignPnlData {
  return {
    campaign_id: "camp-1",
    symbol: "NVDA",
    status: "open",
    opened_date: "2026-09-01",
    closed_date: null,
    legs: [aLeg()],
    option_realized: 0,
    option_unrealized: 115,
    stock_realized: null,
    stock_unrealized: null,
    assigned: false,
    adjusted_cost_basis: null,
    total_net: 115,
    ...overrides,
  };
}

function aLedger(overrides: Partial<LedgerResponseData> = {}): LedgerResponseData {
  return {
    as_of: ISO,
    filters: {
      as_of: ISO,
      symbol: null,
      strategy: null,
      outcome: null,
      since: null,
      until: null,
      book: "all",
    },
    campaigns: [aCampaign()],
    marks_as_of: ISO,
    n_legs: 1,
    ...overrides,
  };
}

describe("LegRow", () => {
  it("renders an open leg's realised cell as unknown, never as zero", () => {
    render(<LegRow leg={{ ...aLeg(), net_pnl: null, outcome: "still_open" }} />);
    expect(screen.queryByText("$0.00")).toBeNull();
    expect(screen.queryByText("$0")).toBeNull();
    expect(within(screen.getByTestId("realized")).getByText(/n\/a/i)).toBeInTheDocument();
  });

  it("renders a closed leg's realised figure", () => {
    render(<LegRow leg={{ ...aLeg(), net_pnl: 149, outcome: "expired_worthless" }} />);
    expect(within(screen.getByTestId("realized")).getByText("+$149.00")).toBeInTheDocument();
  });

  it("says the figure is gross when commission data is incomplete", () => {
    render(<LegRow leg={{ ...aLeg(), net_pnl: 149, commissions_complete: false }} />);
    expect(screen.getByText(/gross/i)).toBeInTheDocument();
  });

  it("keeps realised and unrealised as separate columns with distinct headers", () => {
    render(
      <table>
        <thead>
          <tr>
            <th>Realized</th>
            <th data-testid="unrealized-header">Unrealized</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <LegRow leg={aLeg()} />
          </tr>
        </tbody>
      </table>,
    );
    expect(screen.getByText("Realized")).toBeInTheDocument();
    expect(screen.getByTestId("unrealized-header")).toHaveTextContent("Unrealized");
  });

  it("renders every numeric column tabular so figures align", () => {
    const { container } = render(<LegRow leg={aLeg()} />);
    expect(container.querySelectorAll(".tabular").length).toBeGreaterThan(0);
  });
});

describe("CampaignRow", () => {
  it("renders collapsed with symbol, status, net and leg count", () => {
    render(<CampaignRow campaign={aCampaign({ legs: [aLeg(), aLeg({ candidate_id: "c2" })] })} />);
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByTestId("campaign-status")).toHaveTextContent(/open/i);
    expect(screen.getByTestId("campaign-leg-count")).toHaveTextContent("2 legs");
    expect(screen.queryByTestId("campaign-legs")).toBeNull();
  });

  it("expands to the legs in order using aria-expanded", () => {
    const legA = aLeg({ candidate_id: "a", strike: 100 });
    const legB = aLeg({ candidate_id: "b", strike: 200 });
    render(<CampaignRow campaign={aCampaign({ legs: [legA, legB] })} />);

    const button = screen.getByRole("button", { name: /NVDA/i });
    expect(button).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const legs = screen.getAllByTestId("leg-row");
    expect(legs).toHaveLength(2);
    expect(legs[0]).toHaveTextContent("100");
    expect(legs[1]).toHaveTextContent("200");
  });
});

describe("LedgerTable", () => {
  it("states that no marks are available rather than showing zeros", () => {
    render(<LedgerTable data={{ ...aLedger(), marks_as_of: null }} />);
    expect(screen.getByText(/no marks available/i)).toBeInTheDocument();
    // every leg's unrealised cell renders n/a — expand the thread to read them
    fireEvent.click(screen.getByRole("button", { name: /NVDA/i }));
    const cells = screen.getAllByTestId("unrealized");
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell).toHaveTextContent(/n\/a/i);
      expect(cell).not.toHaveTextContent("$0");
    }
  });

  it("renders the marks age beside the unrealised column when marks exist", () => {
    render(<LedgerTable data={aLedger()} />);
    expect(screen.queryByText(/no marks available/i)).toBeNull();
  });

  it("renders an open leg's unrealised cell as n/a when no marks exist", () => {
    render(<LedgerTable data={{ ...aLedger(), marks_as_of: null }} />);
    fireEvent.click(screen.getByRole("button", { name: /NVDA/i }));
    const cells = screen.getAllByTestId("unrealized");
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell).toHaveTextContent(/n\/a/i);
      expect(cell).not.toHaveTextContent("$0");
    }
  });

  it("renders one line of text and no icon circle for an empty ledger", () => {
    render(<LedgerTable data={{ ...aLedger(), campaigns: [], n_legs: 0 }} />);
    expect(screen.getByText(/no trades/i)).toBeInTheDocument();
    expect(document.querySelector("svg")).toBeNull();
  });

  it("shows the filter echo so the client can prove what it is looking at", () => {
    render(
      <LedgerTable
        data={{
          ...aLedger(),
          filters: { ...aLedger().filters, symbol: "NVDA", book: "paper" },
        }}
      />,
    );
    expect(screen.getByTestId("ledger-filter-echo")).toHaveTextContent(/NVDA/i);
    expect(screen.getByTestId("ledger-filter-echo")).toHaveTextContent(/paper/i);
  });
});

describe("LedgerFilters", () => {
  it("drives the query string, not client-side array filtering", () => {
    // The parent owns the query string; assert the change fires with the value.
    let seen: Record<string, string> = {};
    render(<LedgerFilters filters={aLedger().filters} onChange={(next) => { seen = next; }} />);
    fireEvent.change(screen.getByLabelText(/^symbol/i), { target: { value: "nvda" } });
    expect(seen["symbol"]).toBe("NVDA");
    expect(Object.keys(seen)).toContain("book");
  });

  it("upper-cases the symbol on change so the URL reads like the API's filter", () => {
    let seen: Record<string, string> = {};
    render(<LedgerFilters filters={aLedger().filters} onChange={(next) => { seen = next; }} />);
    fireEvent.change(screen.getByLabelText(/^symbol/i), { target: { value: "nvda" } });
    expect(seen["symbol"]).toBe("NVDA");
  });

  it("renders the book choices the summary refuses to guess", () => {
    render(<LedgerFilters filters={aLedger().filters} onChange={() => {}} />);
    const select = screen.getByLabelText(/^book/i) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["all", "paper", "live"]);
  });
});