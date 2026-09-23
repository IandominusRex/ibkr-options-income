import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { BreakdownTable } from "./BreakdownTable";
import { SummaryPanel } from "./SummaryPanel";
import type { PnlBucketData, PnlSummaryData } from "./types";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// Task 5.6 — the summary panel and the breakdown tables. Both files' tests
// live in SummaryPanel.test.tsx per the task brief's Files line, the same
// convention LedgerTable.test.tsx set.

const ISO = new Date().toISOString();

function aBucket(overrides: Partial<PnlBucketData> = {}): PnlBucketData {
  return {
    label: "cash_secured_put",
    n_closed: 4,
    realized: 320,
    win_rate: 0.75,
    mean_days_held: 12.5,
    mean_roc_pct: 2.1,
    ...overrides,
  };
}

function aSummary(overrides: Partial<PnlSummaryData> = {}): PnlSummaryData {
  return {
    realized_total: 320,
    unrealized_total: 115,
    commissions_complete: true,
    n_open: 2,
    n_closed: 4,
    win_rate: 0.75,
    by_strategy: [aBucket()],
    by_symbol: [aBucket({ label: "NVDA", n_closed: 4 })],
    best: null,
    worst: null,
    ...overrides,
  };
}

function aSummaryResponse(summary: PnlSummaryData) {
  return {
    as_of: ISO,
    filters: {
      as_of: ISO,
      symbol: null,
      strategy: null,
      outcome: null,
      since: null,
      until: null,
      book: "paper",
    },
    summary,
    marks_as_of: ISO,
  };
}

describe("SummaryPanel", () => {
  it("fetches with the exact qsString the shell composed, not book alone", async () => {
    // Regression: the panel used to build its own `?book=${book}` query,
    // ignoring symbol/strategy/outcome/since/until — so filtering the ledger
    // left the headline totals above it unfiltered, silently disagreeing with
    // the rows the operator was looking at.
    renderWithQuery(<SummaryPanel book="paper" qsString="symbol=NVDA&book=paper" />, {
      "/pnl/summary": aSummaryResponse(aSummary()),
    });
    await screen.findByText("Realized total");
    expect(apiFetchMock.mock.calls.at(-1)?.[0]).toBe("/pnl/summary?symbol=NVDA&book=paper");
  });

  it("renders the headline figures", async () => {
    renderWithQuery(<SummaryPanel book="paper" qsString="book=paper" />, {
      "/pnl/summary": aSummaryResponse(aSummary()),
    });
    expect(await screen.findByText("Realized total")).toBeInTheDocument();
    expect(screen.getByText("Unrealized total")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getAllByText("Closed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Win rate").length).toBeGreaterThan(0);
    expect(screen.getAllByText("75%").length).toBeGreaterThan(0);
  });

  it("renders an unknown win rate as unknown, not as zero percent", async () => {
    renderWithQuery(<SummaryPanel book="paper" qsString="book=paper" />, {
      "/pnl/summary": aSummaryResponse(aSummary({ win_rate: null, n_closed: 0, n_open: 1 })),
    });
    await screen.findByText("Unrealized total");
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.getAllByText(/n\/a/i).length).toBeGreaterThan(0);
  });

  it("treats a mixed book as a choice to make, not as an error", async () => {
    // apiFetch throws ApiError on a non-2xx (lib/api.ts); the mock must too, or
    // the query resolves with a body the panel would try to render.
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path.startsWith("/pnl/summary")) {
        throw new ApiError(
          422,
          JSON.stringify({ detail: { reason: "mixed_book" } }),
        );
      }
      throw new Error(`no mock for ${path}`);
    });
    withClient(<SummaryPanel book="all" qsString="book=all" onBookChange={() => {}} />);
    // The operator has paper and live trades and needs to pick one: a
    // labelled group of book choices, in plain words, no alert chrome.
    expect(
      await screen.findByRole("group", { name: /book/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/both books/i)).toBeInTheDocument();
  });

  it("renders the gross qualifier on the headline realised figure when commissions are incomplete", async () => {
    renderWithQuery(<SummaryPanel book="paper" qsString="book=paper" />, {
      "/pnl/summary": aSummaryResponse(aSummary({ commissions_complete: false })),
    });
    expect(await screen.findByText(/gross/i)).toBeInTheDocument();
  });

  it("renders one line of text for an empty book", async () => {
    renderWithQuery(<SummaryPanel book="paper" qsString="book=paper" />, {
      "/pnl/summary": aSummaryResponse(
        aSummary({
          realized_total: 0,
          unrealized_total: null,
          n_open: 0,
          n_closed: 0,
          win_rate: null,
          by_strategy: [],
          by_symbol: [],
        }),
      ),
    });
    expect(await screen.findByText(/no closed trades/i)).toBeInTheDocument();
  });

  it("links best and worst to their legs in the ledger", async () => {
    const onSelectLeg = vi.fn();
    renderWithQuery(<SummaryPanel book="paper" qsString="book=paper" onSelectLeg={onSelectLeg} />, {
      "/pnl/summary": aSummaryResponse(
        aSummary({
          best: {
            candidate_id: "best-1",
            campaign_id: null,
            symbol: "NVDA 261016 00170000P",
            underlying: "NVDA",
            strategy: "cash_secured_put",
            right: "P",
            strike: 170,
            expiry: "2026-10-16",
            contracts: 1,
            opened_at: ISO,
            closed_at: ISO,
            credit: 150,
            debit: 0,
            commissions: 1,
            commissions_complete: true,
            net_pnl: 149,
            unrealized_pnl: null,
            days_held: 5,
            roc_pct: 0.88,
            annualized_pct: null,
            outcome: "expired_worthless",
            is_live: false,
          },
          worst: {
            candidate_id: "worst-1",
            campaign_id: null,
            symbol: "NVDA 260904 00180000P",
            underlying: "NVDA",
            strategy: "cash_secured_put",
            right: "P",
            strike: 180,
            expiry: "2026-09-04",
            contracts: 1,
            opened_at: ISO,
            closed_at: ISO,
            credit: 100,
            debit: 40,
            commissions: 2.6,
            commissions_complete: true,
            net_pnl: 57.4,
            unrealized_pnl: null,
            days_held: 7,
            roc_pct: 0.52,
            annualized_pct: null,
            outcome: "closed_early",
            is_live: false,
          },
        }),
      ),
    });
    expect(await screen.findByText("best-1")).toBeInTheDocument();
    expect(screen.getByText("worst-1")).toBeInTheDocument();
    expect(screen.getByText(/best and worst closed legs/i)).toBeInTheDocument();

    // The label is a real link into the ledger, not just adjacent text —
    // clicking it hands the shell the actual leg to filter the ledger by.
    const bestLink = screen.getByRole("button", { name: /view nvda p 170\.00 in the ledger/i });
    fireEvent.click(bestLink);
    expect(onSelectLeg).toHaveBeenCalledWith(
      expect.objectContaining({ candidate_id: "best-1", underlying: "NVDA" }),
    );
  });

  it("renders best/worst as plain text, not a control, when nothing can select a leg", async () => {
    renderWithQuery(<SummaryPanel book="paper" qsString="book=paper" />, {
      "/pnl/summary": aSummaryResponse(
        aSummary({
          best: {
            candidate_id: "best-1",
            campaign_id: null,
            symbol: "NVDA 261016 00170000P",
            underlying: "NVDA",
            strategy: "cash_secured_put",
            right: "P",
            strike: 170,
            expiry: "2026-10-16",
            contracts: 1,
            opened_at: ISO,
            closed_at: ISO,
            credit: 150,
            debit: 0,
            commissions: 1,
            commissions_complete: true,
            net_pnl: 149,
            unrealized_pnl: null,
            days_held: 5,
            roc_pct: 0.88,
            annualized_pct: null,
            outcome: "expired_worthless",
            is_live: false,
          },
        }),
      ),
    });
    await screen.findByText("best-1");
    expect(screen.queryByRole("button", { name: /view nvda/i })).toBeNull();
  });
});

describe("BreakdownTable", () => {
  it("renders buckets with n_closed, realised, win rate and mean days held", () => {
    render(<BreakdownTable buckets={[aBucket()]} label="by strategy" />);
    expect(screen.getByText(/by strategy/i)).toBeInTheDocument();
    expect(screen.getByText("cash_secured_put")).toBeInTheDocument();
    expect(screen.getByText("12.5")).toBeInTheDocument(); // mean days held
    expect(screen.getByText("75%")).toBeInTheDocument(); // win rate
  });

  it("renders n/a in the rate columns for a bucket with nothing closed", () => {
    render(
      <BreakdownTable
        buckets={[aBucket({ n_closed: 0, realized: 0, win_rate: null, mean_days_held: null })]}
        label="by symbol"
      />,
    );
    const row = screen.getByRole("row", { name: /0/i });
    expect(within(row).getAllByText(/n\/a/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("0%")).toBeNull();
  });
});