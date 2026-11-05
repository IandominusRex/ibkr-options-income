import { describe, expect, it } from "vitest";
import {
  ageWords,
  assessedHref,
  layoutBar,
  readyFirst,
  reasonSentence,
  sellPutAvailable,
  stockValueHref,
} from "./format";
import type { AssessedResponse, TopItem } from "./types";

function item(over: Partial<TopItem> = {}): TopItem {
  return {
    symbol: "GOOGL",
    list_name: "deep_value",
    verdict: "READY",
    decided_by: "python",
    price: 182.4,
    fair_value: 215,
    entry_ceiling: 190,
    stop: null,
    half_sell: 215,
    mos: 0.151,
    reasons: ["healthy, cheap enough, timing passes"],
    put_ceiling: 190,
    age_days: 1,
    ...over,
  };
}

function assessed(strategy: string, stage: string, strike: number | null, symbol = "GOOGL"): AssessedResponse {
  return {
    as_of: "x",
    run_id: "r1",
    computed_at: null,
    groups: [
      {
        as_of: "x",
        symbol,
        counts: {},
        contracts: [
          {
            as_of: "x", candidate_id: "c1", symbol, strategy, strike, expiry: null, stage: stage as never,
            reasons: [], reasons_text: [], blended_score: 0.7, premium: 2, ideal: null, promotable: true, promote_note: null,
          },
        ],
      },
    ],
  };
}

describe("readyFirst", () => {
  it("puts READY, then WATCH, then WAIT, keeps the API's order inside a verdict and stops at ten", () => {
    const rows = [
      item({ symbol: "W1", verdict: "WAIT" }),
      item({ symbol: "A", verdict: "WATCH" }),
      item({ symbol: "R1", verdict: "READY" }),
      item({ symbol: "R2", verdict: "READY" }),
      ...Array.from({ length: 10 }, (_, i) => item({ symbol: `X${i}`, verdict: "WAIT" })),
    ];
    const out = readyFirst(rows);
    expect(out).toHaveLength(10);
    expect(out.slice(0, 4).map((r) => r.symbol)).toEqual(["R1", "R2", "A", "W1"]);
  });
});

describe("layoutBar", () => {
  it("places known levels in price order along the track and names the unknown one", () => {
    const l = layoutBar(item());
    const pct = Object.fromEntries(l.points.map((p) => [p.kind, p.pct]));
    expect(pct.price).toBeLessThan(pct.ceiling);
    expect(pct.ceiling).toBeLessThan(pct.fair);
    expect(l.unknown).toEqual(["Stop"]);
  });

  it("merges the half sale into fair value when they are the same price", () => {
    const l = layoutBar(item());
    const fair = l.points.find((p) => p.kind === "fair");
    expect(fair?.names).toEqual(["Fair value", "Half sale"]);
    expect(l.points.some((p) => p.kind === "half")).toBe(false);
  });

  it("keeps them apart when the half sale is a different price", () => {
    const l = layoutBar(item({ half_sell: 230 }));
    expect(l.points.find((p) => p.kind === "half")?.value).toBe(230);
    expect(l.points.find((p) => p.kind === "fair")?.names).toEqual(["Fair value"]);
  });

  it("never lets two labels share a lane where they would overlap", () => {
    const l = layoutBar(item({ price: 189, entry_ceiling: 190, fair_value: 191, half_sell: 191, stop: 188 }));
    const byLane = new Map<number, number[]>();
    for (const p of l.points) byLane.set(p.lane, [...(byLane.get(p.lane) ?? []), p.pct]);
    for (const pcts of byLane.values()) {
      const sorted = [...pcts].sort((a, b) => a - b);
      for (let i = 1; i < sorted.length; i++) expect(sorted[i]! - sorted[i - 1]!).toBeGreaterThan(20);
    }
    expect(l.lanes).toBeGreaterThan(1);
  });

  it("never draws an unknown price as a zero point", () => {
    const l = layoutBar(item({ price: null, fair_value: null, half_sell: null, entry_ceiling: null }));
    expect(l.points).toHaveLength(0);
    expect(l.unknown).toEqual(["Price", "Fair value", "Entry ceiling", "Stop", "Half sale"]);
  });
});

describe("reasonSentence", () => {
  it("turns Python's baseline reasons into plain sentences", () => {
    expect(reasonSentence("healthy, cheap enough, timing passes")).toBe("Healthy, cheap enough, and the timing passes.");
    expect(reasonSentence("cheap enough; timing fail")).toBe("Cheap enough, but the timing check is not passing.");
    expect(reasonSentence("price 182.40 above the entry ceiling 190.00")).toBe(
      "The price, $182.40, is above the entry ceiling, $190.00.",
    );
    expect(reasonSentence("health gate failed: health.interest_cover, health.debt_to_equity")).toBe(
      "A health gate failed: interest cover, debt to equity.",
    );
  });

  it("falls back to a capitalised sentence, never a raw code", () => {
    expect(reasonSentence("timing_not_ready")).toBe("The entry timing is not ready.");
    expect(reasonSentence("something odd")).toBe("Something odd.");
  });
});

describe("ageWords", () => {
  it("says how old the file is, and null when the API does not know", () => {
    expect(ageWords(0)).toBe("Scorecard from today");
    expect(ageWords(1)).toBe("Scorecard 1 day old");
    expect(ageWords(4)).toBe("Scorecard 4 days old");
    expect(ageWords(null)).toBeNull();
  });
});

describe("sellPutAvailable", () => {
  it("needs a ceiling and a passed CSP candidate at or under it", () => {
    expect(sellPutAvailable(item(), assessed("cash_secured_put", "passed", 185))).toBe(true);
    expect(sellPutAvailable(item(), assessed("cash_secured_put", "passed", 190))).toBe(true);
  });

  it("is false with no ceiling, no data, a rejected candidate, a covered call or a strike above the ceiling", () => {
    expect(sellPutAvailable(item({ put_ceiling: null }), assessed("cash_secured_put", "passed", 185))).toBe(false);
    expect(sellPutAvailable(item(), undefined)).toBe(false);
    expect(sellPutAvailable(item(), assessed("cash_secured_put", "risk_gate", 185))).toBe(false);
    expect(sellPutAvailable(item(), assessed("covered_call", "passed", 185))).toBe(false);
    expect(sellPutAvailable(item(), assessed("cash_secured_put", "passed", 195))).toBe(false);
    expect(sellPutAvailable(item(), assessed("cash_secured_put", "passed", null))).toBe(false);
    expect(sellPutAvailable(item(), assessed("cash_secured_put", "passed", 185, "AAPL"))).toBe(false);
  });
});

describe("links", () => {
  it("point at the stock page's value block and at the name's assessed CSPs", () => {
    expect(stockValueHref("GOOGL")).toBe("/stock/GOOGL#value-block-GOOGL");
    expect(assessedHref("GOOGL")).toBe("/trades?view=assessed&strategy=csp&symbol=GOOGL");
  });
});
