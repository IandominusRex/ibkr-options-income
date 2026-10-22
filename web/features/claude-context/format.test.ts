import { describe, expect, it } from "vitest";
import {
  cutSentence,
  etLabel,
  leveragedLines,
  percent,
  regimeLine,
  shortDay,
  signedPercent,
} from "./format";
import type { IndexRegime, LeveragedLimit } from "./types";

const index = (over: Partial<IndexRegime> = {}): IndexRegime => ({
  index: "QQQ",
  base: "normal",
  base_date: "2026-10-22",
  since: "2026-10-22",
  base_since: "2026-10-22",
  effective: "normal",
  escalated_by: [],
  eased_by_bottoming: false,
  ...over,
});

describe("etLabel", () => {
  it("writes an instant in New York time with its zone", () => {
    expect(etLabel("2026-10-22T15:00:00Z")).toBe("Oct 22, 11:00 AM ET");
    expect(etLabel("2026-01-05T15:05:00+00:00")).toBe("Jan 5, 10:05 AM ET");
  });
  it("never throws on a missing or unreadable instant", () => {
    expect(etLabel(null)).toBe("time n/a");
    expect(etLabel("not a time")).toBe("time n/a");
  });
});

describe("shortDay", () => {
  it("formats a calendar day without a timezone shift", () => {
    expect(shortDay("2026-10-12")).toBe("Oct 12");
    expect(shortDay("2026-01-01")).toBe("Jan 1");
  });
  it("is n/a for anything that is not a day", () => {
    expect(shortDay("")).toBe("date n/a");
    expect(shortDay("2026-13-45")).toBe("date n/a");
  });
});

describe("percent", () => {
  it("drops a trailing .0 and keeps one decimal otherwise", () => {
    expect(percent(40)).toBe("40%");
    expect(percent(12.5)).toBe("12.5%");
    expect(percent(33.3333)).toBe("33.3%");
    expect(percent(0)).toBe("0%");
  });
  it("signs a move, with a real minus sign, and leaves a genuine zero unsigned", () => {
    expect(signedPercent(1.2)).toBe("+1.2%");
    expect(signedPercent(-2)).toBe("−2.0%");
    expect(signedPercent(0)).toBe("0.0%");
  });
});

describe("regimeLine", () => {
  it("says an unmoved index matches its daily base", () => {
    expect(regimeLine(index())).toBe("Daily base normal.");
  });
  it("names what raised it today", () => {
    expect(regimeLine(index({ base: "cautious", effective: "stressed", escalated_by: ["QQQ -2.9% today"] }))).toBe(
      "Daily base cautious, raised today by QQQ -2.9% today.",
    );
  });
  it("says a bottoming signal eased it one step", () => {
    expect(regimeLine(index({ base: "stressed", effective: "cautious", eased_by_bottoming: true }))).toBe(
      "Daily base stressed, eased one step by a bottoming signal.",
    );
  });
  it("reads the no-data marker as words", () => {
    expect(regimeLine(index({ escalated_by: ["no_data"] }))).toBe("Daily base normal, no market data yet.");
  });
});

describe("leveragedLines", () => {
  const row = (symbol: string, leverage: number, calm: number, stressed: number): LeveragedLimit => ({
    symbol,
    leverage,
    calm_fraction: calm,
    stressed_fraction: stressed,
  });
  it("groups names that share a multiple and a ceiling", () => {
    const lines = leveragedLines([
      row("TQQQ", 3, 0.6, 0.3),
      row("SOXL", 3, 0.6, 0.3),
      row("TSLL", 2, 0.8, 0.5),
    ]);
    expect(lines).toEqual([
      "3x (SOXL, TQQQ): 60% of the regime's size when calm, 30% when the name or its market is under stress.",
      "2x (TSLL): 80% of the regime's size when calm, 50% when the name or its market is under stress.",
    ]);
  });
  it("keeps a name with its own ceiling apart", () => {
    const lines = leveragedLines([row("TQQQ", 3, 0.6, 0.3), row("UPRO", 3, 0.5, 0.25)]);
    expect(lines).toHaveLength(2);
  });
  it("is empty for none", () => {
    expect(leveragedLines([])).toEqual([]);
  });
});

describe("cutSentence", () => {
  it("says whether Claude's cut changes the size sent, and for which account", () => {
    expect(cutSentence("applied", "paper")).toBe("Claude's size cuts: applied (paper).");
    expect(cutSentence("record_only", "live")).toBe("Claude's size cuts: recorded only (live).");
  });

  it("says so when today's circuit breaker has paused the cuts, so the line is true on its own", () => {
    expect(cutSentence("applied", "paper", true)).toBe("Claude's size cuts: applied (paper), paused today.");
    expect(cutSentence("record_only", "live", true)).toBe("Claude's size cuts: recorded only (live), paused today.");
    expect(cutSentence("applied", "paper", false)).toBe("Claude's size cuts: applied (paper).");
  });
});
