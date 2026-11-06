import { describe, expect, it } from "vitest";
import type { ValueList, ValuePlan, ValueTicker } from "@/features/stock-value/types";
import { nameLine, valueLeads, valueLines } from "./stock";

const list = (over: Partial<ValueList> = {}): ValueList => ({
  list_name: "deep_value", baseline_verdict: "READY", verdict: "READY", decided_by: "python",
  fair_value: 200, effective_fair_value: 215, mos: 0.15, required_mos_pct: 30, entry_ceiling: 190,
  entry: "pass", timing: "pass", reasons: [], mos_review: false, methods: [], gates: [],
  size_pct: 3, tranches: 3, ...over,
});

const plan = (over: Partial<ValuePlan> = {}): ValuePlan => ({
  position_id: 1, list_name: "deep_value", shares: 20, avg_cost: 150, next_exit: null, stop: null,
  half_sold: false, fair_value: 200, effective_fair_value: 215, tranches_done: 1, tranches: 3,
  tranche_min_sessions: 5, last_tranche_on: "2026-11-02", ...over,
});

const ticker = (lists: ValueList[], over: Partial<ValueTicker> = {}): ValueTicker => ({
  as_of: "2026-11-05T15:00:00Z", available: true, symbol: "GOOGL", computed: "stored", age_days: 1,
  file: {
    symbol: "GOOGL", as_of: "2026-11-04", company_class: "operating", data_quality: "pass", health: "pass",
    ruleset_version: "v4", ruleset_hash: "be30d1eaa915", lists,
  },
  plan: null,
  ...over,
});

describe("valueLeads", () => {
  it("leads with the value block for a priced list or a held name", () => {
    expect(valueLeads(ticker([list({ verdict: "WAIT" })]))).toBe(true);
    expect(valueLeads(ticker([list({ verdict: "NO" })], { plan: plan() }))).toBe(true);
  });
  it("does not lead for every list No, a name it does not score, no file, or no answer", () => {
    expect(valueLeads(ticker([list({ verdict: "NO" })]))).toBe(false);
    const na = ticker([list()]);
    na.file!.not_applicable_reason = "a fund";
    expect(valueLeads(na)).toBe(false);
    expect(valueLeads(ticker([], { available: false, file: null }))).toBe(false);
    expect(valueLeads(undefined)).toBe(false);
  });
});

describe("valueLines", () => {
  it("draws fair value and the entry ceiling of a priced list", () => {
    expect(valueLines(ticker([list()]))).toEqual([
      { price: 215, title: "Fair value $215.00" },
      { price: 190, title: "Entry ceiling $190.00" },
    ]);
  });
  it("shares one line when the half sale sits at fair value, and draws a stop once there is one", () => {
    expect(valueLines(ticker([list()], { plan: plan({ stop: 140 }) }))).toEqual([
      { price: 215, title: "Fair value, Half sale $215.00" },
      { price: 190, title: "Entry ceiling $190.00" },
      { price: 140, title: "Stop $140.00" },
    ]);
  });
  it("draws no half sale once it is made, and no level it has no number for", () => {
    expect(
      valueLines(ticker([list({ effective_fair_value: null, entry_ceiling: null })], { plan: plan({ half_sold: true }) })),
    ).toEqual([]);
  });
  it("names the list when two lists are priced, and draws nothing for a No list", () => {
    const lines = valueLines(
      ticker([
        list(),
        list({ list_name: "quality_growth", effective_fair_value: 230, entry_ceiling: 200 }),
      ]),
    );
    expect(lines.map((l) => l.title)).toEqual([
      "Fair value (Deep value) $215.00",
      "Entry ceiling (Deep value) $190.00",
      "Fair value (Quality growth) $230.00",
      "Entry ceiling (Quality growth) $200.00",
    ]);
    expect(valueLines(ticker([list({ verdict: "NO" })]))).toEqual([]);
  });
});

describe("nameLine", () => {
  it("joins the name, the exchange and ETF with middle dots", () => {
    expect(nameLine({ name: "SPDR Gold", exchange: "NYSE", is_etf: true })).toBe("SPDR Gold · NYSE · ETF");
    expect(nameLine({ name: "Alphabet Inc.", exchange: null, is_etf: false })).toBe("Alphabet Inc.");
    expect(nameLine(undefined)).toBe("");
  });
});
