import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { SizingRecord } from "./SizingRecord";

const group = (over: Record<string, unknown> = {}) => ({
  key: "scale_in_zone:never_sent", kind: "scale_in_zone", split: "never_sent", count: 2,
  contracts_withheld: 4, resolved: 1, exact: 0, pnl_expiry: 120, pnl_rules: 80, rules_missing: 0,
  applied: null, unapplied: null, ...over,
});
const body = (groups: unknown[], since: string | null = null) => ({ as_of: "", since, groups });
const context = { available: true, claude_cut_mode: "record_only", account_mode: "live", claude_cut_breaker_tripped_today: false };
const serve = (b: unknown, since?: string) =>
  renderWithQuery(<SizingRecord since={since} />, { "/pnl/sizing": b, "/claude/context": context });
const row = async (title: string) => (await screen.findByText(title)).closest("li") as HTMLElement;

describe("SizingRecord", () => {
  it("says there is nothing on record, with no zeros", async () => {
    serve(body([]));
    expect(await screen.findByText("No sizing actions on record yet.")).toBeInTheDocument();
    expect(screen.queryByText("$0")).toBeNull();
  });

  it("names the window in the empty sentence when there is one", async () => {
    serve(body([], "2026-10-15"), "2026-10-15");
    expect(await screen.findByText("No sizing actions on record since 2026-10-15.")).toBeInTheDocument();
  });

  it("lists a kind of action with its counts and its two marks, in the stub face", async () => {
    serve(body([group()]));
    const r = await row("Scale-in ladder · never sent");
    expect(within(r).getByText("2 actions · 1 valued so far · 4 contracts held back")).toBeInTheDocument();
    expect(within(r).getByText("+$120.00")).toBeInTheDocument();
    expect(within(r).getByText("to expiry")).toBeInTheDocument();
    expect(within(r).getByText("+$80.00")).toBeInTheDocument();
    expect(within(r).getByText("exit rules")).toBeInTheDocument();
  });

  it("explains what a positive number means, in words", async () => {
    serve(body([group()]));
    expect(
      await screen.findByText(/A positive number is what the held-back contracts would have earned: the action cost that much/),
    ).toBeInTheDocument();
    expect(screen.getByText(/A negative number is a loss it avoided/)).toBeInTheDocument();
  });

  it("writes a negative mark with a real minus", async () => {
    serve(body([group({ pnl_expiry: -30, pnl_rules: -12 })]));
    const r = await row("Scale-in ladder · never sent");
    expect(within(r).getByText("−$30.00")).toBeInTheDocument();
  });

  it("shows hatched n/a marks, not zeros, when nothing is valued yet", async () => {
    serve(body([group({ resolved: 0, pnl_expiry: 0, pnl_rules: 0, contracts_withheld: 2, count: 1 })]));
    const r = await row("Scale-in ladder · never sent");
    const na = within(r).getAllByText("n/a");
    expect(na).toHaveLength(2);
    na.forEach((el) => expect(el).toHaveClass("hatch"));
    expect(within(r).queryByText("$0.00")).toBeNull();
  });

  it("leaves the exit-rule mark out, and says why, when no valued row has an entry IV", async () => {
    serve(body([group({ resolved: 2, rules_missing: 2 })]));
    const r = await row("Scale-in ladder · never sent");
    expect(within(r).getByText("+$120.00")).toBeInTheDocument();
    expect(within(r).getAllByText("n/a")).toHaveLength(1);
    expect(within(r).getByText("2 valued rows have no entry IV, so their exit-rule mark is left out.")).toBeInTheDocument();
  });

  it("counts a pushed-out line and gives it no money", async () => {
    serve(
      body([
        group({
          key: "cc_breakout_floor:pushed_out", kind: "cc_breakout_floor", split: "pushed_out", count: 1,
          contracts_withheld: null, resolved: null, exact: null, pnl_expiry: null, pnl_rules: null, rules_missing: null,
        }),
      ]),
    );
    const r = await row("Breakout rule · pushed out");
    expect(within(r).getByText("1 action · counted, not valued")).toBeInTheDocument();
    expect(within(r).queryByText("to expiry")).toBeNull();
  });

  it("puts Claude's cuts on one line with the applied and recorded-only counts", async () => {
    serve(
      body([group({ key: "claude_overrides", kind: "claude_cut", split: "overrides", count: 2, applied: 1, unapplied: 1 })]),
    );
    const r = await row("Claude's size cut");
    expect(within(r).getByText("1 applied, 1 recorded only.")).toBeInTheDocument();
  });

  it("says whether Claude's cut is applied or only recorded, from the standing setting", async () => {
    serve(body([group()]));
    expect(await screen.findByText("Claude's size cuts: recorded only (live).")).toBeInTheDocument();
  });

  it("asks for the window it was given", async () => {
    serve(body([group()]), "2026-10-01");
    await screen.findByText("Scale-in ladder · never sent");
    expect(apiFetchMock.mock.calls.map((c) => c[0])).toContain("/pnl/sizing?since=2026-10-01");
  });

  it("says it could not load, and that it tries again", async () => {
    renderWithQuery(<SizingRecord />, { "/claude/context": context });
    expect(await screen.findByText("Could not load the sizing record.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every minute.")).toBeInTheDocument();
  });

  it("keeps each mark's label on one line beside its figure, so a phone narrows the words and not the marks", async () => {
    serve(body([group()]));
    const r = await row("Scale-in ladder · never sent");
    expect(within(r).getByText("to expiry").closest(".tabular")).toHaveClass("shrink-0");
  });
});
