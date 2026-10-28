import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { shortDay } from "@/features/claude-context/format";
import { shiftDay, todayInNewYork } from "@/features/trades/time";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { expiryLabel } from "./calendar";
import { CalendarView } from "./CalendarView";

const today = todayInNewYork();
const expiry = shiftDay(today, 30);
const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const entry = (over: Record<string, unknown> = {}) => ({
  as_of: "", symbol: "AAPL  991120P00180000", underlying: "AAPL", right: "P", strike: 180,
  contracts: 1, short: true, moneyness: "otm", consequence: "expires_worthless",
  assignment_risk: false, ...over,
});
const day = (entries: unknown[], over: Record<string, unknown> = {}) => ({ as_of: "", expiry, dte: 30, entries, ...over });
const calendar = (days: unknown[], over: Record<string, unknown> = {}) => ({
  as_of: new Date().toISOString(), source: "monitor", degraded: false, horizon_days: 45, days, ...over,
});
const event = (on: string) => ({ id: "E1", title: "Earnings", on, evidence: "C1", quote: "q" });
const serve = (cal: unknown, dossiers: unknown[] = []) =>
  renderWithQuery(<CalendarView />, {
    "/portfolio/calendar": cal,
    "/claude/context": { available: true, dossiers },
  });

describe("CalendarView", () => {
  it("groups the contracts by expiry day, with the date, the days left and a sentence for each", async () => {
    serve(calendar([day([entry()])]));
    const card = await screen.findByRole("region", { name: `Expiries on ${expiryLabel(expiry)}` });
    expect(within(card).getByText("30 days left")).toBeInTheDocument();
    expect(within(card).getByText("AAPL $180 put")).toBeInTheDocument();
    expect(within(card).getByText("Short · 1 contract")).toBeInTheDocument();
    expect(within(card).getByText("Expires worthless")).toBeInTheDocument();
  });

  it("writes each consequence, and never calls an unknown one worthless", async () => {
    serve(
      calendar([
        day([
          entry({ symbol: "a", consequence: "assigned" }),
          entry({ symbol: "b", consequence: "called_away" }),
          entry({ symbol: "c", consequence: "unknown" }),
        ]),
      ]),
    );
    expect(await screen.findByText("Assigned: shares change hands")).toBeInTheDocument();
    expect(screen.getByText("Called away: shares are sold")).toBeInTheDocument();
    expect(screen.getByText("Consequence unknown")).toBeInTheDocument();
    expect(screen.queryByText("Expires worthless")).toBeNull();
  });

  it("flags an in-the-money short, and says Assignment likely once when the monitor does", async () => {
    serve(
      calendar([
        day([
          entry({ symbol: "a", moneyness: "itm" }),
          entry({ symbol: "b", underlying: "KO", strike: 60, moneyness: "itm", assignment_risk: true }),
        ]),
      ]),
    );
    expect(await screen.findByText("In the money")).toBeInTheDocument();
    expect(screen.getAllByText("Assignment likely")).toHaveLength(1);
  });

  it("says Expires today and still flags assignment risk on the day itself", async () => {
    serve(calendar([day([entry({ moneyness: "itm", assignment_risk: true })], { expiry: today, dte: 0 })]));
    expect(await screen.findByText("Expires today")).toBeInTheDocument();
    expect(screen.getByText("Assignment likely")).toBeInTheDocument();
    expect(screen.getByText("today")).toBeInTheDocument();
  });

  it("says a moneyness it does not have is n/a, not out of the money", async () => {
    serve(calendar([day([entry({ moneyness: null })])]));
    const row = (await screen.findByText("AAPL $180 put")).closest("li") as HTMLElement;
    expect(within(row).getByText("n/a")).toHaveClass("hatch");
    expect(within(row).queryByText("Out of the money")).toBeNull();
  });

  it("marks a short whose name has a verified event before the expiry, by its date", async () => {
    const on = shiftDay(today, 10);
    serve(calendar([day([entry()])]), [{ symbol: "AAPL", health: "ok", events: [event(on)] }]);
    expect(await screen.findByText(`Event ${shortDay(on)} before expiry`)).toBeInTheDocument();
  });

  it("does not mark a long contract, an event after the expiry, or one already past", async () => {
    const soon = shiftDay(today, 10);
    serve(
      calendar([
        day([
          entry({ symbol: "long", short: false }),
          entry({ symbol: "short" }),
          entry({ symbol: "ko", underlying: "KO", strike: 60 }),
        ]),
      ]),
      [
        { symbol: "AAPL", health: "ok", events: [event(soon)] },
        { symbol: "KO", health: "ok", events: [event(shiftDay(expiry, 5)), event(shiftDay(today, -3))] },
      ],
    );
    // The short AAPL's word proves the notes have loaded; it is the only one on the page.
    await screen.findByText(`Event ${shortDay(soon)} before expiry`);
    expect(screen.getAllByText(/before expiry/)).toHaveLength(1);
  });

  it("asks the API for the chosen horizon", async () => {
    serve(calendar([day([entry()])]));
    await screen.findByText("AAPL $180 put");
    fireEvent.click(screen.getByRole("button", { name: "90 days" }));
    await screen.findByText("AAPL $180 put");
    const calls = apiFetchMock.mock.calls.map((c) => c[0]);
    expect(calls).toContain("/portfolio/calendar?horizon_days=45");
    expect(calls).toContain("/portfolio/calendar?horizon_days=90");
  });

  it("says no snapshot has been captured when the source is none", async () => {
    serve(calendar([], { source: "none", degraded: true }));
    expect(await screen.findByText("No portfolio snapshot has been captured yet.")).toBeInTheDocument();
  });

  it("says no option expires inside the horizon when the reading is real and empty", async () => {
    serve(calendar([], { horizon_days: 14 }));
    expect(await screen.findByText("No option expiries within the next 14 days.")).toBeInTheDocument();
  });

  it("says Delayed and the age when the reading is old", async () => {
    serve(calendar([day([entry()])], { as_of: ago(3), source: "eod", degraded: true }));
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
  });

  it("says it could not load, and that it tries again", async () => {
    renderWithQuery(<CalendarView />, {});
    expect(await screen.findByText("Could not load the calendar.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every 30 seconds.")).toBeInTheDocument();
  });
});
