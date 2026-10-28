import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ClaudeContext } from "@/features/claude-context/types";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { HeldBack } from "./HeldBack";
import { MarketCard } from "./MarketCard";
import { NameFlags } from "./NameFlags";
import { NameNotes } from "./NameNotes";
import { actionTitle, eventBefore, limitSentence, nameFlags, reasonWords, sentSentence } from "./market";

afterEach(cleanup);

// Synthetic data shaped like GET /claude/context and GET /claude/sizing.
const AT = "2026-10-22T15:00:00Z";
const ix = (index: string, effective: string, escalated_by: string[] = []) => ({
  index,
  base: "normal",
  base_date: "2026-10-22",
  since: "2026-10-22",
  base_since: "2026-10-22",
  effective,
  escalated_by,
  eased_by_bottoming: false,
});
const ctx = (over: Record<string, unknown> = {}): ClaudeContext =>
  ({
    as_of: AT,
    available: true,
    picture: {
      version: AT,
      built_at: AT,
      regimes: [],
      facts: [],
      events: [],
      stories: [
        { id: 3, title: "Tariff escalation", started_on: "2026-10-12", description: "Headlines hold the index down.", evidence: ["C41"] },
      ],
      noise: { judged: 12, not_reviewed: 340, promotions: 1 },
      stale: false,
    },
    regime: { as_of: AT, spy: ix("SPY", "normal"), qqq: ix("QQQ", "stressed", ["QQQ -3.1% today"]), changes: [] },
    regime_enabled: true,
    suspended_today: false,
    limits: [
      { index: "SPY", regime: "normal", budget_pct: 100, per_trade_pct: 100, max_new_per_day: null, floor_new_per_day: 0 },
      { index: "QQQ", regime: "stressed", budget_pct: 40, per_trade_pct: 30, max_new_per_day: 3, floor_new_per_day: 1 },
    ],
    claude_cut_breaker_tripped_today: false,
    dropped: [{ cluster_id: 1, headline: "h", reason: "r", judged_at: AT, promoted: true, promoted_move_pct: 1.2 }],
    dropped_total: 14,
    not_reviewed_7d: 1156,
    dossiers: [
      {
        symbol: "AMD",
        kind: "stock",
        health: "weak",
        health_why: ["fails the quality screen"],
        held: true,
        story: "A product launch is due (C1).",
        story_evidence: ["C1"],
        events: [{ id: "AMD:E1", title: "Launch event", on: "2026-10-27", evidence: "C1", quote: "Oct 27" }],
        profile: "Designs chips.",
        facts: [],
        facts_at: AT,
        prose_at: AT,
        stale: false,
      },
    ],
    ...over,
  }) as unknown as ClaudeContext;

describe("market helpers", () => {
  it("says a normal regime leaves new puts at their normal size", () => {
    expect(limitSentence({ index: "SPY", regime: "normal", budget_pct: 100, per_trade_pct: 100, max_new_per_day: null, floor_new_per_day: 0 })).toBe(
      "New puts at their normal size.",
    );
  });
  it("spells out a stressed regime's limits", () => {
    expect(limitSentence({ index: "QQQ", regime: "stressed", budget_pct: 40, per_trade_pct: 30, max_new_per_day: 3, floor_new_per_day: 1 })).toBe(
      "New puts: 40% of the normal budget, 30% per trade, at most 3 a day.",
    );
    expect(limitSentence(undefined)).toBeNull();
  });
  it("spells out the codes in a recorded reason and leaves other text alone", () => {
    expect(reasonWords("stopped by the scale-in ladder (loss_exit_cooldown, scale_in_zone_not_reached)")).toBe(
      "stopped by the scale-in ladder (a loss exit on this name earlier today; the price has not reached the next lower entry zone)",
    );
    expect(reasonWords("Claude cut 3 to 1 (thin premium)")).toBe("Claude cut 3 to 1 (thin premium)");
  });
  it("says how many contracts went", () => {
    expect(sentSentence({ deterministic_contracts: 2, sent_contracts: 0 })).toBe("Held back: 0 of 2 contracts sent.");
    expect(sentSentence({ deterministic_contracts: 3, sent_contracts: 1 })).toBe("Sent 1 of 3 contracts.");
    expect(sentSentence({ deterministic_contracts: 1, sent_contracts: 1 })).toBe("Sent 1 contract.");
  });
  it("titles an action by its contract", () => {
    expect(actionTitle({ underlying: "ASTS", strike: 35, right: "P", expiry: "2026-11-13" })).toBe("ASTS $35 put · Nov 13");
  });
  it("flags weak health and an event inside ten days, nothing else", () => {
    const d = ctx().dossiers?.[0];
    expect(nameFlags(d, "2026-10-22")).toEqual({ weak: true, event: "2026-10-27" });
    expect(nameFlags(d, "2026-10-01")).toEqual({ weak: true, event: null });
    expect(nameFlags(undefined, "2026-10-22")).toEqual({ weak: false, event: null });
  });
});

describe("MarketCard", () => {
  it("shows both regimes as words with what each does to new puts, and three stories on Home", async () => {
    renderWithQuery(<MarketCard variant="home" />, { "/claude/context": ctx() });
    expect(await screen.findByText("Stressed")).toBeTruthy();
    expect(screen.getByText("Normal")).toBeTruthy();
    expect(screen.getByText(/New puts: 40% of the normal budget, 30% per trade, at most 3 a day/)).toBeTruthy();
    expect(screen.getByText("Tariff escalation")).toBeTruthy();
    expect(screen.queryByText(/Claude's description/)).toBeNull();
    expect(screen.getByRole("link", { name: /What Claude knows/ }).getAttribute("href")).toBe("/more/claude");
  });
  it("says the limits are suspended and names Claude's description on News, with the triage line", async () => {
    renderWithQuery(<MarketCard variant="news" />, { "/claude/context": ctx({ suspended_today: true }) });
    expect(await screen.findByText("Suspended today")).toBeTruthy();
    expect(screen.queryByText(/New puts: 40%/)).toBeNull();
    expect(screen.getByText(/Claude's description/)).toBeTruthy();
    expect(screen.getByText(/14 stories judged as noise by Claude \(1 promoted after the market moved\), 1156 not reviewed/)).toBeTruthy();
  });
  it("shows only the regimes on Trades", async () => {
    renderWithQuery(<MarketCard variant="trades" />, { "/claude/context": ctx() });
    expect(await screen.findByText("Stressed")).toBeTruthy();
    expect(screen.queryByText("Tariff escalation")).toBeNull();
  });
  it("says so when the news service has no picture and when no regime is recorded", async () => {
    renderWithQuery(<MarketCard variant="home" />, { "/claude/context": ctx({ available: false, picture: null, regime: null }) });
    expect(await screen.findByText(/No regime recorded yet/)).toBeTruthy();
    expect(screen.getByText(/no market picture/)).toBeTruthy();
  });
  it("says the request failed", async () => {
    renderWithQuery(<MarketCard variant="home" />, {}); // no mocked path: the fetch rejects
    expect(await screen.findByText(/could not be loaded/)).toBeTruthy();
  });
});

describe("NameNotes and NameFlags", () => {
  it("shows a name's notes with Claude's story labelled", async () => {
    renderWithQuery(<NameNotes symbol="amd" />, { "/claude/context": ctx() });
    expect(await screen.findByText(/A product launch is due/)).toBeTruthy();
    expect(screen.getByText("Claude's story")).toBeTruthy();
  });
  it("says a name has no notes yet", async () => {
    renderWithQuery(<NameNotes symbol="ZZZ" />, { "/claude/context": ctx() });
    expect(await screen.findByText(/No notes yet for ZZZ/)).toBeTruthy();
  });
  it("says nothing while the request is out or has failed", () => {
    const { container } = renderWithQuery(<NameNotes symbol="AMD" />, {}); // loading, then rejected
    expect(container.textContent).toBe("");
  });
  it("puts Weak health on a row for a weak name", async () => {
    renderWithQuery(<NameFlags symbol="AMD" />, { "/claude/context": ctx() });
    expect(await screen.findByText("Weak health")).toBeTruthy();
  });
});

describe("HeldBack", () => {
  const action = (over: Record<string, unknown>) => ({
    id: 1,
    created_at: AT,
    underlying: "ASTS",
    right: "P",
    strike: 35,
    expiry: "2026-11-13",
    premium: 2,
    kind: "scale_in_zone",
    regime: "normal",
    deterministic_contracts: 2,
    sent_contracts: 0,
    reason: "stopped by the scale-in ladder (scale_in_zone_not_reached)",
    order_id: null,
    ...over,
  });
  it("lists the day's held-back and trimmed puts in words", async () => {
    const sizing = {
      as_of: AT,
      day: "2026-10-22",
      actions: [action({}), action({ id: 2, underlying: "NVDA", kind: "claude_cut", deterministic_contracts: 3, sent_contracts: 1, regime: "stressed", reason: "Claude cut 3 to 1" })],
    };
    renderWithQuery(<HeldBack day="2026-10-22" strategy="all" isToday />, { "/claude/sizing": sizing });
    expect(await screen.findByText("ASTS $35 put · Nov 13")).toBeTruthy();
    expect(screen.getByText("Scale-in ladder")).toBeTruthy();
    expect(screen.getByText(/the price has not reached the next lower entry zone/)).toBeTruthy();
    expect(screen.getByText("Claude's cut")).toBeTruthy();
    expect(screen.getByText(/Sent 1 of 3 contracts/)).toBeTruthy();
    expect(screen.getByText(/The market was stressed/)).toBeTruthy();
  });
  it("renders nothing on a day with none, and nothing under the CC filter for puts", async () => {
    const sizing = { as_of: AT, day: "2026-10-22", actions: [action({})] };
    const { container } = renderWithQuery(<HeldBack day="2026-10-22" strategy="cc" isToday />, { "/claude/sizing": sizing });
    await waitFor(() => expect(apiFetchMock.mock.calls.length).toBeGreaterThan(0));
    expect(container.textContent).toBe("");
  });
});

describe("eventBefore", () => {
  const dossier = (...on: string[]) =>
    ({
      symbol: "AAPL",
      events: on.map((o, i) => ({ id: `E${i}`, title: "t", on: o, evidence: "C1", quote: "q" })),
    }) as never;
  it("is the nearest verified event from today up to and including the expiry", () => {
    expect(eventBefore(dossier("2026-11-10", "2026-10-27"), "2026-10-23", "2026-11-20")).toBe("2026-10-27");
    expect(eventBefore(dossier("2026-11-20"), "2026-10-23", "2026-11-20")).toBe("2026-11-20");
    expect(eventBefore(dossier("2026-10-23"), "2026-10-23", "2026-11-20")).toBe("2026-10-23");
  });
  it("ignores an event already past or after the expiry", () => {
    expect(eventBefore(dossier("2026-10-20", "2026-11-25"), "2026-10-23", "2026-11-20")).toBeNull();
  });
  it("is null with no notes or no events", () => {
    expect(eventBefore(undefined, "2026-10-23", "2026-11-20")).toBeNull();
    expect(eventBefore(dossier(), "2026-10-23", "2026-11-20")).toBeNull();
  });
});
