import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ClaudeContextPage } from "./ClaudeContextPage";
import type { ClaudeContext, Dossier, Dropped, IndexRegime } from "./types";

afterEach(cleanup);

// All data below is synthetic: shaped like GET /claude/context, not read from the account.

const AT = "2026-10-22T15:00:00Z"; // 11:00 AM ET

const index = (over: Partial<IndexRegime> & Pick<IndexRegime, "index">): IndexRegime => ({
  base: "normal",
  base_date: "2026-10-22",
  since: "2026-10-22",
  base_since: "2026-10-22",
  effective: "normal",
  escalated_by: [],
  eased_by_bottoming: false,
  ...over,
});

const dossier = (symbol: string, over: Partial<Dossier> = {}): Dossier => ({
  symbol,
  kind: "stock",
  health: "strong",
  health_why: ["passes the quality screen"],
  held: false,
  story: `${symbol} is launching a new product line next week (C8123).`,
  story_evidence: ["C8123"],
  events: [
    {
      id: `${symbol}:E1`,
      title: "Product launch event",
      on: "2026-10-29",
      evidence: "C8123",
      quote: "The company will unveil it at its event on Oct 29.",
    },
  ],
  profile: "A social-media and AI company; ad revenue and capex drive the shares.",
  facts: [{ id: `${symbol}:F1`, label: "RSI14", display: "RSI 52" }],
  facts_at: AT,
  prose_at: "2026-10-22T13:00:00Z",
  stale: false,
  ...over,
});

const dropped = (id: number, over: Partial<Dropped> = {}): Dropped => ({
  cluster_id: id,
  headline: `Synthetic headline ${id}`,
  reason: "a rehash of last week's story",
  judged_at: "2026-10-21T19:00:00Z",
  promoted: false,
  promoted_move_pct: null,
  ...over,
});

const base = (over: Partial<ClaudeContext> = {}): ClaudeContext => ({
  as_of: AT,
  available: true,
  picture: {
    version: AT,
    built_at: AT,
    regimes: [
      { index: "SPY", effective: "normal", base: "normal", eased_by_bottoming: false, suspended: false, as_of: AT },
      { index: "QQQ", effective: "stressed", base: "cautious", eased_by_bottoming: false, suspended: false, as_of: AT },
    ],
    regime_source: "trading",
    facts: [
      { label: "VIX", value: "VIX 23.4" },
      { label: "QQQ today", value: "QQQ -2.9%" },
    ],
    seasonality: { month: 10, avg_return_pct: 1.2, up_share: 0.6, years: 5 },
    events: ["FOMC Wed 14:00 ET"],
    stories: [
      {
        id: 3,
        title: "Tariff escalation",
        started_on: "2026-10-12",
        description: "Tariff headlines keep the index under its 50-day average.",
        evidence: ["C41", "F2"],
      },
    ],
    noise: { judged: 12, not_reviewed: 340, promotions: 1 },
    stale: false,
  },
  regime: {
    as_of: AT,
    spy: index({ index: "SPY" }),
    qqq: index({ index: "QQQ", base: "cautious", effective: "stressed", escalated_by: ["QQQ -2.9% today"] }),
    changes: [],
  },
  regime_enabled: true,
  suspended_today: false,
  limits: [
    { index: "SPY", regime: "normal", budget_pct: 100, per_trade_pct: 100, max_new_per_day: null, floor_new_per_day: 0 },
    { index: "QQQ", regime: "stressed", budget_pct: 40, per_trade_pct: 30, max_new_per_day: 3, floor_new_per_day: 1 },
  ],
  leveraged_enabled: true,
  leveraged: [
    { symbol: "TQQQ", leverage: 3, calm_fraction: 0.6, stressed_fraction: 0.3 },
    { symbol: "SOXL", leverage: 3, calm_fraction: 0.6, stressed_fraction: 0.3 },
    { symbol: "TSLL", leverage: 2, calm_fraction: 0.8, stressed_fraction: 0.5 },
  ],
  claude_cut_mode: "applied",
  claude_cut_breaker_tripped_today: false,
  account_mode: "paper",
  calls: [
    { kind: "trade_review", label: "Trade review", blocks: ["Market picture", "Your book", "Name notes", "News", "Candidates"] },
    { kind: "roll_review", label: "Roll review", blocks: ["Market picture", "Name notes", "Position", "Live quote", "System proposal"] },
    { kind: "eod_journal", label: "EOD journal", blocks: ["Market picture", "Today's trades"] },
  ],
  dropped: [dropped(1), dropped(2, { promoted: true, promoted_move_pct: 1.2, reason: "local story" })],
  dropped_total: 2,
  not_reviewed_7d: 340,
  dossiers: [dossier("META", { held: true }), dossier("TQQQ", { kind: "leveraged_etf", health: "n/a", health_why: [] })],
  without_notes: ["AMZN", "AVGO"],
  ...over,
});

const serve = (ctx: ClaudeContext) => renderWithQuery(<ClaudeContextPage />, { "/claude/context": ctx });

const card = (name: string) => screen.getByRole("region", { name });

describe("What Claude knows", () => {
  it("shows both regimes and the CSP limits", async () => {
    serve(base());
    const spy = within(await screen.findByRole("group", { name: "SPY regime" }));
    const regime = card("Regime and limits");
    expect(spy.getByRole("heading", { name: "SPY" })).toBeInTheDocument();
    expect(spy.getByText("Normal").getAttribute("data-tone")).toBe("neutral");
    expect(spy.getByText("Daily base normal.")).toBeInTheDocument();
    expect(spy.getByText("No limit")).toBeInTheDocument();
    const qqq = within(screen.getByRole("group", { name: "QQQ regime" }));
    expect(qqq.getByText("Stressed").getAttribute("data-tone")).toBe("flag");
    expect(qqq.getByText("Daily base cautious, raised today by QQQ -2.9% today.")).toBeInTheDocument();
    // Budget 40%, per trade 30%, three a day, one guaranteed lot
    expect(qqq.getByText("40% of normal")).toBeInTheDocument();
    expect(qqq.getByText("30% of normal")).toBeInTheDocument();
    expect(qqq.getByText("3")).toBeInTheDocument();
    expect(qqq.getByText("1")).toBeInTheDocument();
    expect(within(regime).getByText(/Recorded Oct 22, 11:00 AM ET/)).toBeInTheDocument();
  });

  it("says the limits are suspended today", async () => {
    serve(base({ suspended_today: true }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(regime.getByText("Suspended today")).toBeInTheDocument();
    expect(regime.getByText(/not applied today/)).toBeInTheDocument();
  });

  it("says when the regime limits are switched off in config", async () => {
    serve(base({ regime_enabled: false }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(regime.getByText("Off in config")).toBeInTheDocument();
  });

  it("says no regime has been recorded, with a hatched n/a, rather than calling it normal", async () => {
    serve(base({ regime: null, limits: [] }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(regime.getByText(/No regime recorded yet/)).toBeInTheDocument();
    expect(regime.queryByText("Normal")).toBeNull();
    expect(regime.getByText("n/a").className).toContain("hatch");
  });

  it("shows n/a for an index whose limits could not be read", async () => {
    serve(base({ limits: [] }));
    const qqq = within(await screen.findByRole("group", { name: "QQQ regime" }));
    expect(qqq.getByText("Stressed")).toBeInTheDocument();
    expect(qqq.getByText("n/a").className).toContain("hatch");
    expect(qqq.getByText(/could not be read from the config/)).toBeInTheDocument();
  });

  it("labels seasonality as a weak signal", async () => {
    serve(base());
    const picture = within(await screen.findByRole("region", { name: "Market picture" }));
    fireEvent.click(picture.getByRole("button", { name: /The numbers and what is coming/ }));
    expect(picture.getByText("Weak signal")).toBeInTheDocument();
    expect(picture.getByText(/SPY averaged \+1\.2% in October \(5-year average\), up in 60% of those years\./)).toBeInTheDocument();
    expect(picture.getByText("FOMC Wed 14:00 ET")).toBeInTheDocument();
    expect(picture.getByText("F1")).toBeInTheDocument();
    expect(picture.getByText("VIX 23.4")).toBeInTheDocument();
  });

  it("shows the stories with their start date, and Claude's description labelled as Claude's", async () => {
    serve(base());
    const picture = within(await screen.findByRole("region", { name: "Market picture" }));
    expect(picture.getByText("Tariff escalation")).toBeInTheDocument();
    expect(picture.getByText("since Oct 12")).toBeInTheDocument();
    expect(picture.getByText("Claude's description")).toBeInTheDocument();
    expect(picture.getByText("Tariff headlines keep the index under its 50-day average.")).toBeInTheDocument();
    expect(picture.getByText("Evidence: C41, F2")).toBeInTheDocument();
    expect(picture.getByText("Rebuilt Oct 22, 11:00 AM ET")).toBeInTheDocument();
    expect(picture.getByText(/Regimes in this picture: SPY normal, QQQ stressed/)).toBeInTheDocument();
  });

  it("shows a story with no description as its title alone, with no label", async () => {
    const ctx = base();
    ctx.picture!.stories = [{ id: 4, title: "Oil supply", started_on: "2026-10-15", description: "", evidence: [] }];
    serve(ctx);
    const picture = within(await screen.findByRole("region", { name: "Market picture" }));
    expect(picture.getByText("Oil supply")).toBeInTheDocument();
    expect(picture.queryByText("Claude's description")).toBeNull();
  });

  it("shows a stale picture as stale", async () => {
    const ctx = base();
    ctx.picture!.stale = true;
    serve(ctx);
    const picture = within(await screen.findByRole("region", { name: "Market picture" }));
    expect(picture.getByText("Stale")).toBeInTheDocument();
    expect(picture.getByText(/Stale since Oct 22, 11:00 AM ET/)).toBeInTheDocument();
    expect(picture.getByText(/out of date/)).toBeInTheDocument();
  });

  it("says when the news service estimated the regime", async () => {
    const ctx = base();
    ctx.picture!.regime_source = "news";
    serve(ctx);
    const picture = within(await screen.findByRole("region", { name: "Market picture" }));
    expect(picture.getByText(/estimated by the news service/)).toBeInTheDocument();
  });

  it("says there are no stories when none are tracked", async () => {
    const ctx = base();
    ctx.picture!.stories = [];
    serve(ctx);
    const picture = within(await screen.findByRole("region", { name: "Market picture" }));
    expect(picture.getByText("No stories are being tracked.")).toBeInTheDocument();
  });

  it("lists a tile per Claude call with its blocks", async () => {
    serve(base());
    const calls = within(await screen.findByRole("region", { name: "What each Claude call reads" }));
    const lists = calls.getAllByRole("list", { name: /reads$/ });
    expect(lists.map((l) => l.getAttribute("aria-label"))).toEqual([
      "Trade review reads",
      "Roll review reads",
      "EOD journal reads",
    ]);
    const trade = within(calls.getByRole("list", { name: "Trade review reads" }));
    expect(trade.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Market picture",
      "Your book",
      "Name notes",
      "News",
      "Candidates",
    ]);
    expect(calls.getByText("EOD journal")).toBeInTheDocument();
    // the chips are not controls
    expect(calls.queryAllByRole("button")).toHaveLength(0);
  });

  it("shows dropped stories with reasons and promotions", async () => {
    serve(base());
    const dropped = within(await screen.findByRole("region", { name: "Dropped as noise" }));
    expect(dropped.getByText("Synthetic headline 1")).toBeInTheDocument();
    expect(dropped.getByText("Claude's reason: a rehash of last week's story")).toBeInTheDocument();
    expect(dropped.getByText("Promoted")).toBeInTheDocument();
    expect(dropped.getByText("The market moved +1.2% after it.")).toBeInTheDocument();
    expect(dropped.getByText("Claude's reason: local story")).toBeInTheDocument();
    expect(dropped.getByText("340 stories were not reviewed: they fell outside the batch Claude judged.")).toBeInTheDocument();
  });

  it("says one unreviewed story in the singular", async () => {
    serve(base({ not_reviewed_7d: 1 }));
    const region = within(await screen.findByRole("region", { name: "Dropped as noise" }));
    expect(region.getByText("1 story was not reviewed: it fell outside the batch Claude judged.")).toBeInTheDocument();
  });

  it("writes a falling market move with a real minus sign", async () => {
    serve(base({ dropped: [dropped(1, { promoted: true, promoted_move_pct: -2 })], dropped_total: 1 }));
    const region = within(await screen.findByRole("region", { name: "Dropped as noise" }));
    expect(region.getByText("The market moved −2.0% after it.")).toBeInTheDocument();
  });

  it("shows the first five dropped stories and the rest on request", async () => {
    const many = Array.from({ length: 8 }, (_, i) => dropped(i + 1));
    serve(base({ dropped: many, dropped_total: 8 }));
    const region = within(await screen.findByRole("region", { name: "Dropped as noise" }));
    expect(region.queryByText("Synthetic headline 6")).toBeNull();
    expect(region.getByText("Synthetic headline 5")).toBeInTheDocument();
    fireEvent.click(region.getByRole("button", { name: "Show all 8" }));
    expect(region.getByText("Synthetic headline 8")).toBeInTheDocument();
    expect(region.queryByRole("button", { name: /Show all/ })).toBeNull();
  });

  it("says how many dropped stories the list leaves out", async () => {
    serve(base({ dropped: [dropped(1)], dropped_total: 130 }));
    const region = within(await screen.findByRole("region", { name: "Dropped as noise" }));
    expect(region.getByText("Showing the latest 1 of 130.")).toBeInTheDocument();
  });

  it("says nothing was dropped, and does not claim a reason that was not recorded", async () => {
    serve(base({ dropped: [], dropped_total: 0, not_reviewed_7d: 0 }));
    const region = within(await screen.findByRole("region", { name: "Dropped as noise" }));
    expect(region.getByText("Nothing was dropped in the last 7 days.")).toBeInTheDocument();
    expect(region.queryByText(/not reviewed/)).toBeNull();
  });

  it("shows n/a, not a blank, for a dropped story whose reason is not on record", async () => {
    serve(base({ dropped: [dropped(1, { reason: "", promoted: true, promoted_move_pct: 1.5 })], dropped_total: 1 }));
    const region = within(await screen.findByRole("region", { name: "Dropped as noise" }));
    expect(region.getByText(/Claude's reason:/).textContent).toContain("n/a");
  });

  it("says the news service has no picture yet when unavailable", async () => {
    serve(base({ available: false, picture: null, dropped: [], dossiers: [], dropped_total: 0, not_reviewed_7d: 0, without_notes: [] }));
    expect(await screen.findByText(/The news service has not written anything yet, so there is no picture/)).toBeInTheDocument();
    // the regime still shows: it comes from the trading service
    expect(screen.getByRole("group", { name: "QQQ regime" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Dropped as noise" })).getByText(/news service has not written anything yet/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Names" })).getByText(/no notes/)).toBeInTheDocument();
    // the tiles are static and still answer
    expect(screen.getByRole("region", { name: "What each Claude call reads" })).toBeInTheDocument();
  });

  it("says there is no picture yet when the news service is up but has built none", async () => {
    serve(base({ picture: null }));
    expect(await screen.findByText("No picture has been built yet.")).toBeInTheDocument();
  });

  it("lists each name's notes with Claude's text and the profile labelled", async () => {
    serve(base());
    const names = within(await screen.findByRole("region", { name: "Names" }));
    const meta = within(names.getByRole("listitem", { name: "META" }));
    expect(meta.getByRole("heading", { name: "META" })).toBeInTheDocument();
    expect(meta.getByText("Held")).toBeInTheDocument();
    expect(meta.getByText("Stock")).toBeInTheDocument();
    expect(meta.getByText("Health: strong")).toBeInTheDocument();
    expect(meta.getByText(/passes the quality screen/)).toBeInTheDocument();
    expect(meta.getByText("Claude's story")).toBeInTheDocument();
    expect(meta.getByText("META is launching a new product line next week (C8123).")).toBeInTheDocument();
    expect(meta.getByText("Evidence: C8123")).toBeInTheDocument();
    expect(meta.getByText("Upcoming")).toBeInTheDocument();
    expect(meta.getByText("Oct 29 · Product launch event")).toBeInTheDocument();
    expect(meta.getByText("Notes rebuilt Oct 22, 9:00 AM ET")).toBeInTheDocument();
    // the profile and the numbers sit behind a disclosure, the profile labelled as Claude's
    fireEvent.click(meta.getByRole("button", { name: /Profile and numbers/ }));
    expect(meta.getByText("Claude's summary, general knowledge")).toBeInTheDocument();
    expect(meta.getByText("A social-media and AI company; ad revenue and capex drive the shares.")).toBeInTheDocument();
    expect(meta.getByText("RSI 52")).toBeInTheDocument();
    expect(meta.getByText(/The company will unveil it at its event on Oct 29\./)).toBeInTheDocument();
    // a leveraged ETF: kind in words, and no health label (a fund has none, which is not "unknown")
    const tqqq = within(names.getByRole("listitem", { name: "TQQQ" }));
    expect(tqqq.getByText("Leveraged ETF")).toBeInTheDocument();
    expect(tqqq.queryByText(/Health/)).toBeNull();
    expect(tqqq.queryByText("Held")).toBeNull();
  });

  it("hatches only the n/a, not the words, when a stock's health could not be worked out", async () => {
    serve(base({ dossiers: [dossier("ZZZ", { health: "unknown", health_why: ["no fundamentals"] })] }));
    const zzz = within(await screen.findByRole("listitem", { name: "ZZZ" }));
    const na = zzz.getByText("n/a");
    expect(na.className).toContain("hatch");
    expect(na.parentElement?.textContent).toBe("Health n/a");
    expect(zzz.getByText("no fundamentals")).toBeInTheDocument();
  });

  const REPORTED = "Reported in news (not computed by the system)";
  const quote = (text: string, cluster_id: string) => ({ text, cluster_id });

  it("shows the figures quoted from the news under their own label, apart from Claude's story", async () => {
    serve(
      base({
        dossiers: [
          dossier("META", {
            reported: [
              quote("Analysts see glasses sales of $5.2 billion", "C8123"),
              quote("Launch set for 3 markets", "C8124"),
            ],
          }),
        ],
      }),
    );
    const meta = within(await screen.findByRole("listitem", { name: "META" }));
    const label = meta.getByText(REPORTED);
    expect(label.className).toContain("text-muted"); // the same small label face as "Claude's story"
    const list = meta.getByRole("list", { name: REPORTED });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]!.textContent).toContain("Analysts see glasses sales of $5.2 billion");
    expect(items[0]!.textContent).toContain("Evidence: C8123");
    expect(items[1]!.textContent).toContain("Launch set for 3 markets");
    expect(items[1]!.textContent).toContain("Evidence: C8124");
    // never inside the story's own paragraph
    const storyLabel = meta.getByText("Claude's story");
    const storyP = storyLabel.parentElement!;
    expect(storyP.textContent).not.toContain("$5.2 billion");
    expect(storyP.contains(label)).toBe(false);
    // and it comes after the story, before the upcoming dates
    const order = Array.from(meta.getByText("Claude's story").closest("li")!.querySelectorAll("p, ul, div"));
    expect(order.findIndex((n) => n.contains(label))).toBeGreaterThan(order.findIndex((n) => n === storyP));
  });

  it("shows nothing for a name with no reported figures", async () => {
    serve(base({ dossiers: [dossier("META", { reported: [] }), dossier("AMD"), dossier("NVDA", { reported: undefined })] }));
    const names = within(await screen.findByRole("region", { name: "Names" }));
    expect(names.queryByText(REPORTED)).toBeNull();
    expect(names.queryByRole("list", { name: REPORTED })).toBeNull();
    expect(names.queryByText(/Reported/)).toBeNull();
  });

  it("shows the reported figures even when Claude wrote no story", async () => {
    serve(
      base({
        dossiers: [
          dossier("META", { story: "", story_evidence: [], reported: [quote("Guidance of $5.2 billion", "C8123")] }),
        ],
      }),
    );
    const meta = within(await screen.findByRole("listitem", { name: "META" }));
    expect(meta.getByText(/No story right now/)).toBeInTheDocument();
    expect(meta.getByText(REPORTED)).toBeInTheDocument();
    expect(meta.getByText(/Guidance of \$5\.2 billion/)).toBeInTheDocument();
  });

  it("keeps a long quoted figure inside the row", async () => {
    const long = `Analysts see sales of $5.2 billion ${"x".repeat(80)}`;
    serve(base({ dossiers: [dossier("META", { reported: [quote(long, "C8123")] })] }));
    const meta = within(await screen.findByRole("listitem", { name: "META" }));
    expect(meta.getByText(long).className).toContain("break-words");
    // the evidence id never splits from its label ("Evidence:" on one line, "C8123" on the next)
    expect(within(meta.getByRole("list", { name: REPORTED })).getByText("Evidence: C8123").className).toContain("whitespace-nowrap");
  });

  it("keeps the order the API gives: held names first", async () => {
    serve(base({ dossiers: [dossier("META", { held: true }), dossier("AMD"), dossier("NVDA")] }));
    const names = within(await screen.findByRole("region", { name: "Names" }));
    const headings = names.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["META", "AMD", "NVDA"]);
  });

  it("flags a weak health label, and says no story rather than leaving a blank", async () => {
    serve(
      base({
        dossiers: [dossier("GME", { health: "weak", health_why: ["free cash flow negative"], story: "", story_evidence: [], events: [] })],
      }),
    );
    const gme = within(await screen.findByRole("listitem", { name: "GME" }));
    expect(gme.getByText("Health: weak").getAttribute("data-tone")).toBe("flag");
    expect(gme.getByText(/free cash flow negative/)).toBeInTheDocument();
    expect(gme.getByText(/No story right now/)).toBeInTheDocument();
    expect(gme.queryByText("Upcoming")).toBeNull();
  });

  it("shows stale notes as stale, and says when no notes were written yet", async () => {
    serve(
      base({
        dossiers: [dossier("META", { stale: true }), dossier("AMD", { prose_at: null, story: "", story_evidence: [], events: [], profile: "" })],
      }),
    );
    const meta = within(await screen.findByRole("listitem", { name: "META" }));
    expect(meta.getByText("Stale")).toBeInTheDocument();
    expect(meta.getByText(/Notes are from Oct 22, 9:00 AM ET; the last rebuild failed\./)).toBeInTheDocument();
    const amd = within(screen.getByRole("listitem", { name: "AMD" }));
    expect(amd.getByText("Claude has not written notes for this name yet.")).toBeInTheDocument();
  });

  it("names the covered names that have no notes yet", async () => {
    serve(base());
    const names = within(await screen.findByRole("region", { name: "Names" }));
    expect(names.getByText("No notes yet for AMZN, AVGO.")).toBeInTheDocument();
  });

  it("shows the leveraged-ETF ceilings and Claude's cut mode", async () => {
    serve(base());
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(
      regime.getByText("3x (SOXL, TQQQ): 60% of the regime's size when calm, 30% when the name or its market is under stress."),
    ).toBeInTheDocument();
    expect(
      regime.getByText("2x (TSLL): 80% of the regime's size when calm, 50% when the name or its market is under stress."),
    ).toBeInTheDocument();
    expect(regime.getByText("Claude's size cuts: applied (paper).")).toBeInTheDocument();
  });

  it("says a recorded-only cut in live, and a switched-off ceiling", async () => {
    serve(base({ claude_cut_mode: "record_only", account_mode: "live", leveraged_enabled: false, leveraged: [] }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(regime.getByText("Claude's size cuts: recorded only (live).")).toBeInTheDocument();
    expect(regime.getByText("Leveraged-ETF ceilings are switched off.")).toBeInTheDocument();
  });

  it("shows today's circuit breaker as an amber flag word, before the index blocks", async () => {
    serve(base({ claude_cut_breaker_tripped_today: true }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    const cut = regime.getByText("Claude's size cuts: applied (paper), paused today.");
    const word = regime.getByText("Cuts paused today");
    // a flag word like "Suspended today": a status word in the flag tone, not a control, with the
    // cause and the effect as a sentence beside it
    expect(word.getAttribute("data-tone")).toBe("flag");
    const line = word.closest("p");
    expect(line).not.toBeNull();
    expect(line?.textContent).toContain("The circuit breaker tripped");
    expect(line?.textContent).toContain("recorded but not applied until tomorrow");
    expect(word.closest("button, a")).toBeNull();
    // it sits with the other flag lines, ahead of the regime blocks, so it is in the first screen
    // at phone width instead of below both indices; the cut-mode sentence stays where it was
    const spy = regime.getByRole("group", { name: "SPY regime" });
    expect(word.compareDocumentPosition(spy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(word.compareDocumentPosition(cut) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("stacks the flag lines in one order: off in config, suspended, cuts paused", async () => {
    serve(base({ regime_enabled: false, suspended_today: true, claude_cut_breaker_tripped_today: true }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    const off = regime.getByText("Off in config");
    const suspended = regime.getByText("Suspended today");
    const paused = regime.getByText("Cuts paused today");
    expect(off.compareDocumentPosition(suspended) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(suspended.compareDocumentPosition(paused) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const w of [off, suspended, paused]) expect(w.getAttribute("data-tone")).toBe("flag");
  });

  it("shows the breaker word in the same way as the suspended word, and no other state as plain text", async () => {
    serve(base({ suspended_today: true, claude_cut_breaker_tripped_today: true }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    const suspended = regime.getByText("Suspended today");
    const paused = regime.getByText("Cuts paused today");
    expect(paused.getAttribute("data-tone")).toBe(suspended.getAttribute("data-tone"));
    expect(paused.className).toBe(suspended.className);
    // the old plain sentence is gone: the state is the word, not a colon-joined line of body ink
    expect(regime.queryByText("Cuts paused today: the circuit breaker tripped.")).toBeNull();
    expect(regime.queryByText(/today: the circuit/)).toBeNull();
  });

  it("says nothing about the breaker while it has not tripped", async () => {
    serve(base({ claude_cut_breaker_tripped_today: false }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(regime.getByText("Claude's size cuts: applied (paper).")).toBeInTheDocument();
    expect(regime.queryByText(/circuit breaker/)).toBeNull();
    expect(regime.queryByText(/paused/i)).toBeNull();
    expect(regime.queryByText("Cuts paused today")).toBeNull();
  });

  it("says nothing about the breaker when the field is absent (an older API)", async () => {
    const older: Partial<ClaudeContext> = { ...base() };
    delete older.claude_cut_breaker_tripped_today;
    serve(older as ClaudeContext);
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(regime.getByText("Claude's size cuts: applied (paper).")).toBeInTheDocument();
    expect(regime.queryByText("Cuts paused today")).toBeNull();
  });

  it("says the breaker tripped whatever the cut mode, and keeps the regime card whole", async () => {
    serve(base({ claude_cut_mode: "record_only", account_mode: "live", claude_cut_breaker_tripped_today: true }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(regime.getByText("Claude's size cuts: recorded only (live), paused today.")).toBeInTheDocument();
    expect(regime.getByText("Cuts paused today").getAttribute("data-tone")).toBe("flag");
    expect(regime.getByText("Claude can lower the size of a put the system opens on its own. It can never raise it.")).toBeInTheDocument();
  });

  it("says the breaker tripped even with no regime recorded yet", async () => {
    serve(base({ regime: null, limits: [], claude_cut_breaker_tripped_today: true }));
    const regime = within(await screen.findByRole("region", { name: "Regime and limits" }));
    expect(regime.getByText(/No regime recorded yet/)).toBeInTheDocument();
    expect(regime.getByText("Cuts paused today").getAttribute("data-tone")).toBe("flag");
  });

  it("holds its place while loading", async () => {
    serve(base());
    expect(screen.getByRole("status", { name: "Loading what Claude knows" })).toBeInTheDocument();
    await screen.findByRole("region", { name: "Regime and limits" });
    expect(screen.queryByRole("status", { name: "Loading what Claude knows" })).toBeNull();
  });

  it("says how to retry when the request fails, and retries", async () => {
    let calls = 0;
    apiFetchMock.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) throw new Error("boom");
      return base();
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ClaudeContextPage />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/Could not load what Claude knows/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Regime and limits" })).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it("only reads: no lime, no link or button that acts on an order, a limit or a size", async () => {
    const { container } = serve(base());
    await screen.findByRole("region", { name: "Regime and limits" });
    expect(container.querySelector(".bg-primary")).toBeNull();
    const names = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(names.join(" | ")).not.toMatch(/approve|reject|halt|resume|promote|roll|save/i);
  });

  it("follows the copy rules: no em dash, none of the banned words", async () => {
    const { container } = serve(base({ suspended_today: true }));
    await screen.findByRole("region", { name: "Regime and limits" });
    fireEvent.click(screen.getAllByRole("button", { name: /Profile and numbers/ })[0]!);
    const text = container.textContent ?? "";
    expect(text).not.toContain("\u2014"); // the em dash
    expect(text).not.toMatch(/seamless|robust|unlock|elevate/i);
  });

  it("keeps the copy rules in the breaker sentence and the reported line", async () => {
    const { container } = serve(
      base({
        claude_cut_breaker_tripped_today: true,
        dossiers: [dossier("META", { reported: [quote("Guidance of $5.2 billion", "C8123")] })],
      }),
    );
    await screen.findByRole("region", { name: "Regime and limits" });
    const text = container.textContent ?? "";
    expect(text).not.toContain("\u2014");
    expect(text).not.toMatch(/seamless|robust|unlock|elevate/i);
    expect(container.querySelector(".bg-primary")).toBeNull();
  });

  it("links back to More", async () => {
    serve(base());
    expect(await screen.findByRole("link", { name: "More" })).toHaveAttribute("href", "/more");
    expect(screen.getByRole("heading", { level: 1, name: "What Claude knows" })).toBeInTheDocument();
  });
});
