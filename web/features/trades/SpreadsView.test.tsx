import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { SpreadsView } from "./SpreadsView";

const item = (letter: string, position: string, short: number, long: number) => ({
  letter, position, side: "put", short_strike: short, long_strike: long, width: 5, contracts: 21,
  credit_mid: 0.25, credit_after_costs: 0.144, max_loss_per_contract_usd: 475, short_delta: -0.14,
  spot: 767.29, dist_spot_pts: 5.29, dist_em_multiple: 1.49, be_nominal_exits: 0.9493,
});

const pick = (over: Record<string, unknown> = {}) => ({
  pick_id: 2, created_at: "2026-10-15T15:00:00Z", book_mode: "paper", choice: "A",
  reason: "A keeps the most room under spot.", fallback_reason: null, executed_letter: "A",
  send_rejected: false, send_reasons: [], filled: true, model: "claude-sonnet-5-5",
  regime: "negative", side: "put", plan_bias: null, event_flag: false, menu_readable: true,
  menu: [item("A", "inside", 763, 758), item("B", "baseline", 762, 757)], spread_id: "s1", ...over,
});

const position = (over: Record<string, unknown> = {}) => ({
  as_of: "", spread_id: "s1", mode: "paper", side: "put", expiry: "2026-10-15", short_strike: 763,
  long_strike: 758, width: 5, contracts_opened: 21, contracts: 0, entry_credit: 0.25,
  entry_commission: 27.3, opened_at: "2026-10-15T15:01:00Z", status: "closed", exit_debit: 0.05,
  exit_commission: 27.3, exit_reason: "profit_take", closed_at: "2026-10-15T17:00:00Z",
  realized_pnl_usd: 365.4, ...over,
});

const baseline = position({ spread_id: "b1", mode: "baseline", short_strike: 762, long_strike: 757, realized_pnl_usd: -120 });

const day = (over: Record<string, unknown> = {}) => ({
  as_of: "", available: true, underlying: "SPY", mode: "paper", ai_enabled: true, day: "2026-10-15",
  previous_day: "2026-10-09", next_day: null, picks: [pick()], positions: [position()], ...over,
});

describe("SpreadsView", () => {
  it("leads with the day's spreads, paper and baseline books side by side, results signed", async () => {
    renderWithQuery(<SpreadsView />, { "/spreads/picks": day({ positions: [position(), baseline] }) });
    const book = await screen.findByRole("region", { name: "Spreads opened this day" });
    const paper = within(book).getByRole("region", { name: "Paper book" });
    const base = within(book).getByRole("region", { name: /Baseline book/ });
    expect(within(paper).getByText("+$365.40")).toBeInTheDocument();
    expect(within(base).getByText("−$120.00")).toBeInTheDocument();
    // The position page reads the paper book only: a baseline spread is not a link.
    expect(within(paper).getByRole("link", { name: /SPY 763\/758 put spread/ })).toHaveAttribute("href", "/positions/SPY/spread-s1");
    expect(within(base).queryByRole("link")).toBeNull();
  });

  it("keeps the menu Claude saw under the spread it opened, collapsed, with the pick marked and the reason labelled", async () => {
    renderWithQuery(<SpreadsView />, { "/spreads/picks": day() });
    const paper = await screen.findByRole("region", { name: "Paper book" });
    const toggle = within(paper).getByRole("button", { name: /The menu Claude saw/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(within(paper).getByText("Sent A, the 763/758 put spread, 21 contracts. It filled.")).toBeInTheDocument();
    expect(within(paper).getByText("Claude's view:")).toBeInTheDocument();
    const rows = within(within(paper).getByRole("list", { name: "Menu" })).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Claude's pick")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Sent")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Baseline")).toBeInTheDocument();
  });

  it("labels a pick that was refused before it traded as chosen, not sent, with the reason", async () => {
    renderWithQuery(<SpreadsView />, {
      "/spreads/picks": day({
        picks: [pick({ pick_id: 3, spread_id: null, filled: false, send_rejected: true, send_reasons: ["stale_pick"] })],
        positions: [],
      }),
    });
    const other = await screen.findByRole("region", { name: "Other picks" });
    const card = within(other).getByRole("article", { name: "SPY · Claude picked A" });
    fireEvent.click(within(card).getByRole("button", { name: /The menu Claude saw/ }));
    const rows = within(within(card).getByRole("list", { name: "Menu" })).getAllByRole("listitem");
    expect(within(rows[0]).queryByText("Sent")).toBeNull();
    expect(within(rows[0]).getByText("Chosen, did not trade")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Did not trade: stale pick.")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Claude's pick")).toBeInTheDocument();
  });

  it("lists picks without a spread on this page under Other picks", async () => {
    renderWithQuery(<SpreadsView />, {
      "/spreads/picks": day({
        picks: [pick(), pick({ pick_id: 1, choice: "skip", executed_letter: null, filled: false, spread_id: null, reason: "Event risk." })],
      }),
    });
    const other = await screen.findByRole("region", { name: "Other picks" });
    const card = within(other).getByRole("article", { name: "SPY · Claude skipped" });
    expect(within(card).getByText("Claude chose not to trade this menu. Nothing was sent.")).toBeInTheDocument();
    expect(within(other).queryByRole("article", { name: "SPY · Claude picked A" })).toBeNull();
  });

  it("says an unreadable menu could not be read and still shows the other picks", async () => {
    renderWithQuery(<SpreadsView />, {
      "/spreads/picks": day({
        picks: [pick(), pick({ pick_id: 1, menu_readable: false, menu: [], choice: "B", executed_letter: "B", spread_id: null, filled: false, send_rejected: true })],
      }),
    });
    const other = await screen.findByRole("region", { name: "Other picks" });
    const bad = within(other).getByRole("article", { name: "SPY · Claude picked B" });
    // The unknown texture is a small mark beside the words: hatching the sentence itself drew
    // same-coloured lines through every letter (da-vinci finish, 2026-10-19).
    const note = within(bad).getByText("This menu could not be read.");
    expect(note).not.toHaveClass("hatch");
    expect(note).toHaveClass("text-unknown");
    expect(note.parentElement?.querySelector(".hatch")).not.toBeNull();
    expect(screen.getByRole("region", { name: "Paper book" })).toBeInTheDocument();
  });

  it("says the book could not be read, rather than showing an empty day", async () => {
    renderWithQuery(<SpreadsView />, { "/spreads/picks": day({ available: false, picks: [], positions: [] }) });
    expect(await screen.findByText("The spreads book could not be read right now.")).toBeInTheDocument();
    expect(screen.queryByText("No spread was opened on this day.")).toBeNull();
  });

  it("says when the picker is off", async () => {
    renderWithQuery(<SpreadsView />, { "/spreads/picks": day({ ai_enabled: false, picks: [] }) });
    expect(await screen.findByText(/Claude's picker is off/)).toBeInTheDocument();
  });

  it("says when nothing was opened and no menu was offered", async () => {
    renderWithQuery(<SpreadsView />, { "/spreads/picks": day({ picks: [], positions: [] }) });
    expect(await screen.findByText("No spread was opened on this day.")).toBeInTheDocument();
    expect(screen.getByText("No menu was offered on this day.")).toBeInTheDocument();
  });

  it("steps to the previous day with activity, and back to today", async () => {
    renderWithQuery(<SpreadsView />, {
      "/spreads/picks?day=2026-10-09": day({ day: "2026-10-09", previous_day: null, next_day: null, picks: [], positions: [] }),
      "/spreads/picks": day(),
    });
    expect(await screen.findByRole("heading", { name: /Thu, Oct 15/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next day with spreads activity" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous day with spreads activity" }));
    expect(await screen.findByRole("heading", { name: /Fri, Oct 9/ })).toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => c[0] === "/spreads/picks?day=2026-10-09")).toBe(true);
    // No later day has activity, so next goes back to today.
    fireEvent.click(screen.getByRole("button", { name: "Back to today" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: /Thu, Oct 15/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Previous day with spreads activity" }));
    expect(await screen.findByRole("heading", { name: /Fri, Oct 9/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: /Thu, Oct 15/ })).toBeInTheDocument());
  });

  it("sends nothing: no request but reads", async () => {
    renderWithQuery(<SpreadsView />, { "/spreads/picks": day() });
    await screen.findByRole("region", { name: "Spreads opened this day" });
    const writes = apiFetchMock.mock.calls.filter((c) => (c[1] as RequestInit | undefined)?.method);
    expect(writes).toHaveLength(0);
  });
});
