import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SystemPanel } from "./SystemPanel";
import type {
  ScoreBucketData,
  SignalCorrelationData,
  SystemPerformanceResponse,
  VerdictAgreementData,
} from "./types";

// Task 6.2 — the score-vs-outcome surface. Unlike SummaryPanel (self-fetches),
// SystemPanel is presentational: PnlShell owns the useQuery call and the
// since/until window state, the same split EquityChart already uses.

const ISO = new Date().toISOString();
const READONLY_NOTE =
  "Read-only: re-derive scoring_weights.yaml from this evidence by hand (the fence " +
  "forbids any automatic feedback into the engine).";
const CLOSED_ONLY_NOTE =
  "Closed (executed+settled) trades only — rejected/unfilled candidates carry no P&L.";

function aBucket(overrides: Partial<ScoreBucketData> = {}): ScoreBucketData {
  return { label: "70-80", n: 12, win_rate: 0.6, mean_pnl: 45.5, total_pnl: 546, ...overrides };
}

function aCorrelation(overrides: Partial<SignalCorrelationData> = {}): SignalCorrelationData {
  return {
    signal: "blended_score",
    n: 12,
    pearson_r: 0.32,
    low_half_mean_pnl: 10,
    high_half_mean_pnl: 60,
    ...overrides,
  };
}

function anAgreement(overrides: Partial<VerdictAgreementData> = {}): VerdictAgreementData {
  return {
    n_closed: 12,
    n_agreed: 9,
    agreement_rate: 0.75,
    claude_win_rate: 0.7,
    baseline_win_rate: 0.55,
    ...overrides,
  };
}

function aReport(overrides: Partial<SystemPerformanceResponse> = {}): SystemPerformanceResponse {
  const base: SystemPerformanceResponse = {
    as_of: ISO,
    since: null,
    until: null,
    report: {
      n_closed: 12,
      period_start: null,
      period_end: null,
      blended_score_buckets: [aBucket()],
      component_buckets: [aBucket({ label: "iv:high" })],
      signal_correlations: [aCorrelation()],
      notes: [CLOSED_ONLY_NOTE, READONLY_NOTE],
    },
    agreement: anAgreement(),
  };
  return { ...base, ...overrides };
}

function emptyReport(): SystemPerformanceResponse {
  return {
    as_of: ISO,
    since: null,
    until: null,
    report: {
      n_closed: 0,
      period_start: null,
      period_end: null,
      blended_score_buckets: [],
      component_buckets: [],
      signal_correlations: [],
      notes: [
        CLOSED_ONLY_NOTE,
        READONLY_NOTE,
        "No closed trades in window — nothing to correlate yet.",
      ],
    },
    agreement: {
      n_closed: 0,
      n_agreed: 0,
      agreement_rate: null,
      claude_win_rate: null,
      baseline_win_rate: null,
    },
  };
}

function reportWithBucket(overrides: Partial<ScoreBucketData>): SystemPerformanceResponse {
  const base = aReport();
  return { ...base, report: { ...base.report, blended_score_buckets: [aBucket(overrides)] } };
}

describe("SystemPanel", () => {
  it("renders every note in full and in order", () => {
    render(<SystemPanel data={aReport()} />);
    aReport().report.notes!.forEach((n) => expect(screen.getByText(n)).toBeInTheDocument());
  });

  it("offers no way to change a weight", () => {
    const { container } = render(<SystemPanel data={aReport()} />);
    const controls = container.querySelectorAll("button, input, select");
    const windowControls = container.querySelectorAll('[data-role="window-control"]');
    expect(controls.length).toBe(windowControls.length);
    expect(windowControls.length).toBe(2); // since + until, nothing else
  });

  it("says when a bucket is too small to be evidence", () => {
    render(<SystemPanel data={reportWithBucket({ label: "80-90", n: 3 })} />);
    expect(screen.getByText(/small sample/i)).toBeInTheDocument();
  });

  it("renders nothing but the note when no trades have closed", () => {
    render(<SystemPanel data={emptyReport()} />);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText(/no closed trades in window/i)).toBeInTheDocument();
  });

  it("renders blended-score buckets as a table with label, n, win rate, mean and total P&L", () => {
    render(<SystemPanel data={aReport()} />);
    const heading = screen.getByText(/blended score/i);
    const table = heading.closest("div") as HTMLElement;
    expect(within(table).getByText("70-80")).toBeInTheDocument();
    expect(within(table).getByText("60%")).toBeInTheDocument();
  });

  it("renders component buckets in their own, separately labelled table", () => {
    render(<SystemPanel data={aReport()} />);
    expect(screen.getByText(/score components/i)).toBeInTheDocument();
    expect(screen.getByText("iv:high")).toBeInTheDocument();
  });

  it("renders correlations with pearson_r and the low/high split", () => {
    render(<SystemPanel data={aReport()} />);
    const table = screen.getByText(/signal correlations/i).closest("div") as HTMLElement;
    expect(within(table).getByText("blended_score")).toBeInTheDocument();
    expect(within(table).getByText("0.32")).toBeInTheDocument();
  });

  it("renders a null pearson_r and null half-splits as n/a", () => {
    const base = aReport();
    render(
      <SystemPanel
        data={{
          ...base,
          report: {
            ...base.report,
            signal_correlations: [
              aCorrelation({ pearson_r: null, low_half_mean_pnl: null, high_half_mean_pnl: null }),
            ],
          },
        }}
      />,
    );
    expect(screen.getAllByText(/n\/a/i).length).toBeGreaterThan(0);
  });

  it("renders the agreement block with claude and baseline win rates side by side", () => {
    render(<SystemPanel data={aReport()} />);
    const block = screen.getByTestId("agreement-block");
    expect(within(block).getByText("70%")).toBeInTheDocument();
    expect(within(block).getByText("55%")).toBeInTheDocument();
  });

  it("renders a null agreement_rate as n/a, not zero", () => {
    const base = aReport();
    render(<SystemPanel data={{ ...base, agreement: anAgreement({ agreement_rate: null }) }} />);
    const block = screen.getByTestId("agreement-block");
    expect(within(block).getAllByText(/n\/a/i).length).toBeGreaterThan(0);
    expect(within(block).queryByText("0%")).toBeNull();
  });
});
