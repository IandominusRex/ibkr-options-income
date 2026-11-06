import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { ValueBlock } from "./ValueBlock";
import type { ValueTicker } from "./types";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

function ticker(over: Partial<ValueTicker> = {}): ValueTicker {
  return {
    as_of: "2026-11-05T15:00:00Z",
    available: true,
    symbol: "GOOGL",
    computed: "stored",
    age_days: 1,
    file: {
      symbol: "GOOGL", as_of: "2026-11-04", computed_at: "2026-11-04T22:00:00Z", universe: "trading",
      company_class: "operating", data_quality: "pass", health: "pass", price: 182.4,
      ruleset_version: "v4", ruleset_hash: "be30d1eaa915", reverse_dcf_implied_growth: 0.062,
      gates: [
        { id: "health.interest_cover", group: "health", state: "pass", value: 12.5, threshold: 3, detail: "" },
        { id: "health.debt_to_equity", group: "health", state: "fail", value: 2.4, threshold: 1.5, detail: "high leverage" },
        { id: "dq.filing_age", group: "data_quality", state: "unknown", value: null, threshold: null, detail: "" },
      ],
      lists: [
        {
          list_name: "deep_value", baseline_verdict: "WAIT", verdict: "READY", decided_by: "claude",
          fair_value: 200, effective_fair_value: 215, mos: 0.151, required_mos_pct: 30, entry_ceiling: 190,
          entry: "pass", timing: "fail", reasons: ["timing_not_ready"], mos_review: false, size_pct: 3, tranches: 3,
          methods: [
            { method: "B", value: 210, state: "ok", detail: "", used: true, median: true },
            { method: "A", value: 190, state: "ok", detail: "", used: true, median: false },
            { method: "C", value: null, state: "absent", detail: "", used: false, median: false },
          ],
          gates: [{ id: "timing.above_50d", group: "timing", state: "fail", value: 182.4, threshold: 190, detail: "" }],
        },
        {
          list_name: "quality_growth", baseline_verdict: "NO", verdict: "NO", decided_by: "python",
          fair_value: null, effective_fair_value: null, mos: null, required_mos_pct: 25, entry_ceiling: null,
          entry: "fail", timing: "unknown", reasons: [], mos_review: false, methods: [], gates: [], size_pct: null,
          tranches: 3,
        },
      ],
      metrics: {}, adjustments: [],
    },
    claude: {
      source: "claude",
      read_at: "2026-11-04T23:00:00Z",
      lists: [
        {
          list_name: "deep_value", verdict: "READY", why: "Cheap against cash flow", fair_value: 215, python_fair_value: 200,
          cap_applied: true, unreliable: null, backend: "cli", clamps: ["growth 0.2000 -> 0.1000"],
          drivers: [{ name: "growth", chosen: 0.2, used: 0.1, clamped: true, bound: "hi" }],
        },
      ],
      notes: [
        { kind: "thesis", text: "Search ads keep compounding." },
        { kind: "bear_case", text: "A ruling could force a breakup." },
        { kind: "review", text: "INTACT: nothing broke." },
      ],
      kill_triggers: [{ name: "debt_to_equity", threshold: 1.5, actual: 0.9, state: "far", distance_pct: 40 }],
      facts: [{ text: "Buybacks were $60B", quote: "repurchased $60.0 billion", filing: "0001652044-26-000012" }],
    },
    reevaluations: [
      {
        id: 3, list_name: "deep_value", session: "2026-10-28", last_session: "2026-10-27", severity: "major",
        triggers: [{ kind: "move", severity: "major", detail: "down 9%" }],
        plan_before: { stop: 120 }, plan_after: { stop: 135 }, review_state: null,
      },
    ],
    plan: {
      position_id: 1, list_name: "deep_value", shares: 20, avg_cost: 150, next_exit: { kind: "sell_half", level: 215 },
      stop: 140, half_sold: false, fair_value: 200, effective_fair_value: 215, tranches_done: 1, tranches: 3,
      tranche_min_sessions: 5, last_tranche_on: "2026-10-20",
    },
    ...over,
  };
}

function show(t: ValueTicker = ticker(), extra: Record<string, unknown> = {}) {
  return renderWithQuery(<ValueBlock symbol="googl" />, { "/value/GOOGL": t, ...extra });
}

describe("ValueBlock", () => {
  it("opens with the verdict per list, who decided it, fair value against price, margin of safety and the plan", async () => {
    show();
    const deep = await screen.findByRole("group", { name: "Deep value" });
    expect(within(deep).getByText("Ready")).toBeInTheDocument();
    expect(within(deep).getByText(/Claude's verdict decides this\. Python's baseline is Wait\./)).toBeInTheDocument();
    expect(within(deep).getByText(/Fair value \$215\.00/)).toBeInTheDocument();
    expect(within(deep).getByText(/price \$182\.40/)).toBeInTheDocument();
    expect(within(deep).getByText(/margin of safety 15\.1%/)).toBeInTheDocument();
    const quality = screen.getByRole("group", { name: "Quality growth" });
    expect(within(quality).getByText("No")).toBeInTheDocument();
    expect(within(quality).getByText("Python's rules decide this.")).toBeInTheDocument();
    expect(screen.getByText("stop $140.00 · sell half at $215.00 · then trail")).toBeInTheDocument();
  });

  it("says the value book has not written anything, in one sentence, when it is unavailable", async () => {
    show(ticker({ available: false, file: null, claude: null, plan: null, reevaluations: [] }));
    expect(await screen.findByText("The value book has not written anything yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run Claude/ })).toBeNull();
  });

  it("says a fresh recompute was worked out just now", async () => {
    show(ticker({ computed: "now", age_days: 0 }));
    expect(await screen.findByText("Worked out just now from the latest filings")).toBeInTheDocument();
  });

  it("says it is fetching the filings while the file is pending", async () => {
    show(ticker({ computed: "pending", file: null, claude: null, plan: null, reevaluations: [] }));
    expect(await screen.findByText("Fetching the filings")).toBeInTheDocument();
  });

  it("shows the file's age", async () => {
    show();
    expect(await screen.findByText("Scorecard of Nov 4, 2026, 1 day old")).toBeInTheDocument();
  });

  it("answers 'is the business still doing its job' with gates (value and bar) and the kill triggers and their distance", async () => {
    show();
    const biz = await screen.findByRole("region", { name: "Is the business still doing its job?" });
    expect(within(biz).getAllByText("Debt to equity")).toHaveLength(2);
    expect(within(biz).getByText(/reads 2\.4, bar 1\.5/)).toBeInTheDocument();
    expect(within(biz).getByText("Fail")).toBeInTheDocument();
    expect(within(biz).getByText(/Kill triggers Claude set, checked by Python/)).toBeInTheDocument();
    expect(within(biz).getByText(/40% of room left before it fires/)).toBeInTheDocument();
  });

  it("answers 'what is it worth' with the methods and the median marked, then Claude's fair value, drivers, clamp and cap", async () => {
    show();
    const worth = await screen.findByRole("region", { name: "What is it worth?" });
    expect(within(worth).getByText("Median")).toBeInTheDocument();
    expect(within(worth).getByText("Cash-flow DCF")).toBeInTheDocument();
    expect(within(worth).getByText(/not available/)).toBeInTheDocument();
    expect(within(worth).getByText(/Claude's fair value/)).toBeInTheDocument();
    expect(within(worth).getByText(/Growth: Claude chose 0\.2, Python used 0\.1/)).toBeInTheDocument();
    expect(within(worth).getByText(/1\.5x cap/)).toBeInTheDocument();
    expect(within(worth).getByText(/6\.2%/)).toBeInTheDocument();
    expect(within(worth).getByText(/Python's baseline: Wait/)).toBeInTheDocument();
    expect(within(worth).getByText(/Claude's verdict: Ready/)).toBeInTheDocument();
  });

  it("does not set the verdicts side by side when they agree", async () => {
    const t = ticker();
    t.file!.lists![0]!.baseline_verdict = "READY";
    t.file!.lists![0]!.decided_by = "python";
    show(t);
    const worth = await screen.findByRole("region", { name: "What is it worth?" });
    expect(within(worth).queryByText(/Python's baseline: /)).toBeNull();
  });

  it("answers 'how much, and when' with timing, what the regime asks and the held position", async () => {
    show();
    const size = await screen.findByRole("region", { name: "How much, and when?" });
    expect(within(size).getByText(/margin of safety asked now is 30%/)).toBeInTheDocument();
    expect(within(size).getByText(/the entry timing is not ready/)).toBeInTheDocument();
    expect(within(size).getByText(/Entry ceiling \$190\.00/)).toBeInTheDocument();
    expect(within(size).getByText(/20 shares at an average cost of \$150\.00/)).toBeInTheDocument();
  });

  it("lists a held name's re-evaluations as a short dated list", async () => {
    show();
    const list = await screen.findByRole("list", { name: "Re-evaluations" });
    expect(within(list).getByText(/Oct 28, 2026/)).toBeInTheDocument();
    expect(within(list).getByText(/move: down 9%/)).toBeInTheDocument();
    expect(within(list).getByText(/stop \$120\.00 to \$135\.00/)).toBeInTheDocument();
  });

  it("labels every piece of Claude's text as Claude's, with the scorecard date it was read against", async () => {
    show();
    expect(await screen.findByText("Claude's thesis")).toBeInTheDocument();
    expect(screen.getByText("Search ads keep compounding.")).toBeInTheDocument();
    expect(screen.getByText("Claude's bear case")).toBeInTheDocument();
    expect(screen.getByText("Claude's review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Claude's analysis" })).toBeInTheDocument();
    expect(screen.getByText(/Read Nov 4, 2026, against the scorecard of Nov 4, 2026/)).toBeInTheDocument();
  });

  it("says Claude has not read the name yet, rather than showing nothing", async () => {
    show(ticker({ claude: null }));
    expect(await screen.findByText(/Claude has not read GOOGL yet/)).toBeInTheDocument();
  });

  it("says the value book does not score a name it cannot (a fund, say), with the reason", async () => {
    const t = ticker({ claude: null, plan: null, reevaluations: [] });
    t.file!.not_applicable_reason = "a fund has no earnings to value";
    t.file!.lists = [];
    show(t);
    expect(await screen.findByText(/The value book does not score GOOGL: a fund has no earnings to value\./)).toBeInTheDocument();
  });

  it("draws an unknown price as a hatched n/a, never $0", async () => {
    const t = ticker();
    t.file!.price = null;
    show(t);
    const deep = await screen.findByRole("group", { name: "Deep value" });
    const na = within(deep).getAllByText("n/a").find((el) => el.className.includes("hatch"));
    expect(na).toBeDefined();
    expect(within(deep).queryByText("$0")).toBeNull();
  });

  it("uses no long dash anywhere", async () => {
    const { container } = show();
    await screen.findByText("Claude's thesis");
    expect(container.textContent).not.toContain(String.fromCharCode(0x2014));
  });
});
