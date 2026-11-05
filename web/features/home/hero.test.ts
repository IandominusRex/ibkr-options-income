import { describe, expect, it } from "vitest";
import { changeCaption, chartPoints, heroDelay, heroFigures } from "./hero";
import type { AccountValueSeries } from "./types";

const series: AccountValueSeries = {
  range: "1m",
  points: [
    { at: "2026-10-01T20:00:00Z", value: 100_000 },
    { at: "2026-10-12T20:00:00Z", value: 101_000 },
    { at: "2026-10-13T18:00:00Z", value: 101_500 },
  ],
  latest: 101_500,
  latest_at: "2026-10-13T18:00:00Z",
  previous_close: 101_000,
  change_today: 500,
  change_today_pct: 0.495,
  change: 500,
  change_pct: 0.495,
  change_since: "2026-10-12T20:00:00Z",
};

describe("changeCaption", () => {
  const now = new Date("2026-10-17T16:00:00Z"); // a Saturday
  it("follows the range chip", () => {
    expect(changeCaption({ ...series, range: "1w" }, now)).toBe("past week");
    expect(changeCaption({ ...series, range: "3m" }, now)).toBe("past 3 months");
  });
  it("names the session when the 1d value is not from today", () => {
    const fri = { ...series, range: "1d" as const, latest_at: "2026-10-16T20:00:00Z" };
    expect(changeCaption(fri, now)).toBe("last session (Oct 16, 2026)");
    expect(changeCaption(fri, new Date("2026-10-16T21:00:00Z"))).toBe("today");
  });
});

describe("heroFigures", () => {
  it("shows the latest value and today's change when not scrubbing", () => {
    expect(heroFigures(series, null)).toEqual({ value: 101_500, delta: 500, deltaPct: 0.495, caption: "past month" });
  });
  it("shows the scrubbed point and its change since the range start", () => {
    const f = heroFigures(series, 1);
    expect(f.value).toBe(101_000);
    expect(f.delta).toBe(1_000);
    expect(f.deltaPct).toBeCloseTo(1);
    expect(f.caption).toBe("Oct 12, 2026");
  });
  it("keeps unknowns unknown", () => {
    const empty = { ...series, points: [], latest: null, change: null, change_pct: null };
    expect(heroFigures(empty, null)).toEqual({ value: null, delta: null, deltaPct: null, caption: "past month" });
  });
});

describe("chartPoints", () => {
  const at = (iso: string) => Math.floor(Date.parse(iso) / 1000);
  it("keeps the last point of a second and remembers which input row it was", () => {
    expect(
      chartPoints([
        { at: "2026-10-13T14:00:00.100Z", value: 1 },
        { at: "2026-10-13T14:00:00.900Z", value: 2 },
        { at: "2026-10-13T14:00:05Z", value: 3 },
      ]),
    ).toEqual([
      { time: at("2026-10-13T14:00:00Z"), value: 2, index: 1 },
      { time: at("2026-10-13T14:00:05Z"), value: 3, index: 2 },
    ]);
  });
  it("sorts rows that arrive out of order and lets the later instant win a tie", () => {
    const out = chartPoints([
      { at: "2026-10-13T14:00:09Z", value: 9 },
      { at: "2026-10-13T14:00:01.800Z", value: 18 },
      { at: "2026-10-13T14:00:01.200Z", value: 12 },
    ]);
    expect(out.map((p) => p.value)).toEqual([18, 9]);
    expect(out.map((p) => p.index)).toEqual([1, 0]);
  });
  it("leaves out a point whose timestamp cannot be read instead of handing the chart NaN", () => {
    expect(chartPoints([{ at: "not a date", value: 1 }, { at: "2026-10-13T14:00:00Z", value: 2 }])).toEqual([
      { time: at("2026-10-13T14:00:00Z"), value: 2, index: 1 },
    ]);
    expect(chartPoints([])).toEqual([]);
  });
});

// Final review m5: the hero showed an 11:00 snapshot as today's change at 15:00 with no age,
// while the positions card below flagged the same snapshot table "Delayed". Same rule as that
// card (older than 30 minutes), but only in market hours: after the close and at weekends the
// headline is the last close, which is right, not degraded. Times are New York time, from `now`.
describe("heroDelay", () => {
  const at = (latest_at: string | null, latest: number | null = 101_500) => ({ ...series, latest, latest_at });
  it("gives the age of a headline older than 30 minutes during market hours", () => {
    // Tue Oct 13 2026, EDT: the monitor stopped at 11:00, it is now 15:00.
    expect(heroDelay(at("2026-10-13T15:00:00Z"), new Date("2026-10-13T19:00:00Z"))).toBe("4h ago");
  });
  it("does not flag a fresh headline", () => {
    expect(heroDelay(at("2026-10-13T18:50:00Z"), new Date("2026-10-13T19:00:00Z"))).toBeNull();
    expect(heroDelay(at("2026-10-13T18:30:00Z"), new Date("2026-10-13T19:00:00Z"))).toBeNull();
  });
  it("does not flag the last close after 16:00 New York time", () => {
    expect(heroDelay(at("2026-10-13T20:00:00Z"), new Date("2026-10-13T23:00:00Z"))).toBeNull();
    // Still the evening in New York while it is already the next morning in Singapore.
    expect(heroDelay(at("2026-10-13T20:00:00Z"), new Date("2026-10-14T01:30:00Z"))).toBeNull();
  });
  it("does not flag Friday's close at a weekend", () => {
    expect(heroDelay(at("2026-10-16T20:00:00Z"), new Date("2026-10-17T16:00:00Z"))).toBeNull();
    expect(heroDelay(at("2026-10-16T20:00:00Z"), new Date("2026-10-18T19:00:00Z"))).toBeNull();
  });
  it("reads market hours in New York time on both sides of the clock change", () => {
    // Tue Nov 3 2026 is EST (UTC-5): 14:20Z is 09:20, before the open; 15:00Z is 10:00.
    expect(heroDelay(at("2026-11-02T21:00:00Z"), new Date("2026-11-03T14:20:00Z"))).toBeNull();
    expect(heroDelay(at("2026-11-02T21:00:00Z"), new Date("2026-11-03T15:00:00Z"))).toBe("18h ago");
    // 20:30Z is 15:30 EST, still open; under EDT arithmetic it would read 16:30, closed.
    expect(heroDelay(at("2026-11-03T15:00:00Z"), new Date("2026-11-03T20:30:00Z"))).toBe("5h ago");
  });
  it("never flags an unknown or unreadable headline", () => {
    const now = new Date("2026-10-13T19:00:00Z");
    expect(heroDelay(at(null), now)).toBeNull();
    expect(heroDelay(at("not a time"), now)).toBeNull();
    expect(heroDelay(at("2026-10-13T15:00:00Z", null), now)).toBeNull();
  });
});
