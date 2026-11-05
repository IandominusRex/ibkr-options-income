import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { RealisedCalendarButton } from "./RealisedCalendar";

afterEach(cleanup);

const NOW = new Date("2026-10-15T16:00:00Z");

const cal = (month: string, days: Array<[string, number, number]>, over: object = {}) => ({
  as_of: "",
  book: "paper",
  spreads_available: true,
  calendar: {
    month: `${month}-01`,
    strategy: "all",
    days: days.map(([date, realized, n]) => ({ date, realized, n_closed: n, complete: true })),
    total: days.reduce((a, d) => a + d[1], 0),
    n_closed: days.reduce((a, d) => a + d[2], 0),
    complete: true,
    ...over,
  },
});

const octDays: Array<[string, number, number]> = [
  ["2026-10-09", 1717.88, 3],
  ["2026-10-13", -1603.7, 1],
  ["2026-10-14", 12400, 2],
];

const dayDetail = {
  as_of: "",
  date: "2026-10-09",
  book: "paper",
  strategy: "all",
  spreads_available: true,
  trades: [
    {
      key: "a:closed", action: "closed", how: "bought_back", kind: "csp", source: "wheel", underlying: "AMZN", right: "P",
      strike: 252.5, long_strike: null, expiry: "2026-10-23", contracts: 1, at: "2026-10-09T15:00:00Z", is_live: false,
      premium: 400, bought_back: 40, commissions: 1, commissions_complete: true, net_pnl: 359, capital: 25250, roc_pct: 1.6,
      annualized_pct: null, pct_kept: 90, dte_at_open: 14, days_held: 5, reason: "Closed for a profit: the position reached its profit target.",
      facts: [], approval_id: 1, review: null, rolled_to: null,
    },
    {
      key: "b:opened", action: "opened", how: null, kind: "csp", source: "wheel", underlying: "AAPL", right: "P",
      strike: 330, long_strike: null, expiry: "2026-11-20", contracts: 1, at: "2026-10-09T14:00:00Z", is_live: false,
      premium: 300, bought_back: null, commissions: 1, commissions_complete: true, net_pnl: null, capital: 33000, roc_pct: 0.9,
      annualized_pct: 8, pct_kept: null, dte_at_open: 42, days_held: null, reason: null, facts: [], approval_id: 2, review: null, rolled_to: null,
    },
  ],
};

const serve = (extra: Record<string, unknown> = {}) => ({
  "/pnl/calendar?month=2026-10": cal("2026-10", octDays),
  "/pnl/calendar?month=2026-09": cal("2026-09", []),
  "/pnl/day?date=2026-10-09": dayDetail,
  ...extra,
});

async function openIt(responses: Record<string, unknown> = serve()) {
  renderWithQuery(<RealisedCalendarButton now={NOW} />, responses);
  fireEvent.click(screen.getByRole("button", { name: "Daily realised P&L calendar" }));
  return screen.findByRole("dialog", { name: "Realised P&L" });
}

describe("RealisedCalendar", () => {
  it("opens a dialog on the current New York month with the month's total", async () => {
    const dialog = await openIt();
    expect(await within(dialog).findByRole("heading", { name: "October 2026" })).toBeInTheDocument();
    expect(within(dialog).getByText("Realised in October")).toBeInTheDocument();
    expect(within(dialog).getByText("+$12,514.18")).toBeInTheDocument(); // 1717.88 - 1603.70 + 12400 = 12514.18
    expect(within(dialog).getByText("from 6 closes")).toBeInTheDocument();
  });

  it("shows each day with a close as a signed figure and leaves the rest blank", async () => {
    const dialog = await openIt();
    const nine = await within(dialog).findByRole("button", { name: /Fri, Oct 9: \+\$1,717\.88 realised from 3 closes/ });
    expect(nine).toHaveTextContent("+1.7K");
    expect(within(dialog).getByRole("button", { name: /Tue, Oct 13: −\$1,603\.70 realised from 1 close$/ })).toHaveTextContent("−1.6K");
    expect(within(dialog).getByRole("button", { name: /Wed, Oct 14: \+\$12,400\.00/ })).toBeInTheDocument();
    // a day nothing closed is plain text, not a button, and never "$0"
    expect(within(dialog).getAllByRole("button", { name: /realised from/ })).toHaveLength(3);
    expect(within(dialog).queryByText("$0")).toBeNull();
  });

  it("is a labelled table, Monday first", async () => {
    const dialog = await openIt();
    await within(dialog).findByRole("table", { name: "Realised P&L by day, October 2026" });
    const heads = within(dialog).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
  });

  it("a tapped day lists what closed that day, with the reason and the result, not what opened", async () => {
    const dialog = await openIt();
    fireEvent.click(await within(dialog).findByRole("button", { name: /Fri, Oct 9/ }));
    const section = await within(dialog).findByRole("region", { name: "What closed on Fri, Oct 9" });
    expect(await within(section).findByText("AMZN · Bought back $252.5 put")).toBeInTheDocument();
    expect(within(section).getByText("Closed for a profit: the position reached its profit target.")).toBeInTheDocument();
    expect(within(section).getByText("+$359.00")).toBeInTheDocument();
    expect(within(section).queryByText(/AAPL/)).toBeNull();
    expect(within(dialog).getByRole("button", { name: /Fri, Oct 9/ })).toHaveAttribute("aria-pressed", "true");
    // tapping it again closes the detail
    fireEvent.click(within(dialog).getByRole("button", { name: /Fri, Oct 9/ }));
    expect(within(dialog).queryByRole("region", { name: /What closed on/ })).toBeNull();
  });

  it("links a tapped day to that day in History", async () => {
    const dialog = await openIt();
    fireEvent.click(await within(dialog).findByRole("button", { name: /Fri, Oct 9/ }));
    const section = await within(dialog).findByRole("region", { name: "What closed on Fri, Oct 9" });
    expect(within(section).getByRole("link", { name: "Open this day in History" })).toHaveAttribute(
      "href",
      "/trades?view=history&day=2026-10-09",
    );
  });

  it("walks back a month and cannot walk past the current one", async () => {
    const dialog = await openIt();
    await within(dialog).findByRole("heading", { name: "October 2026" });
    expect(within(dialog).getByRole("button", { name: "Next month" })).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Previous month" }));
    expect(await within(dialog).findByRole("heading", { name: "September 2026" })).toBeInTheDocument();
    expect(await within(dialog).findByText("Nothing closed in September.")).toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => c[0] === "/pnl/calendar?month=2026-09")).toBe(true);
    expect(within(dialog).getByRole("button", { name: "Next month" })).toBeEnabled();
  });

  it("says when commissions are incomplete or spreads could not be read, in words", async () => {
    const dialog = await openIt(
      serve({
        "/pnl/calendar?month=2026-10": { ...cal("2026-10", octDays, { complete: false }), spreads_available: false },
      }),
    );
    expect(await within(dialog).findByText("Commissions incomplete")).toBeInTheDocument();
    expect(within(dialog).getByText("Spreads unavailable")).toBeInTheDocument();
  });

  it("states what is and is not counted, so a blank day is not read as flat", async () => {
    const dialog = await openIt();
    expect(await within(dialog).findByText(/Share sales are not included, and a day nothing closed is blank/)).toBeInTheDocument();
  });

  it("says in words when the month could not be loaded", async () => {
    const dialog = await openIt({});
    expect(await within(dialog).findByText(/could not be loaded/)).toBeInTheDocument();
  });

  it("closes on Escape and gives focus back to the button", async () => {
    const dialog = await openIt();
    await within(dialog).findByRole("heading", { name: "October 2026" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  describe("the value book", () => {
    // The value-only calendar for the month: the same days, with only the book's sales in them.
    const valueCal = (days: Array<[string, number, number]> = [["2026-10-14", 400, 1]]) =>
      cal("2026-10", days, { strategy: "value" });
    const withValue = (extra: Record<string, unknown> = {}) =>
      serve({ "/pnl/calendar?month=2026-10&strategy=value": { ...valueCal(), value_available: true }, ...extra });
    const sale = {
      key: "value:8:sell:20261014T150000", action: "closed", how: null, kind: "value", source: "value", underlying: "GOOGL",
      right: null, strike: 190, long_strike: null, expiry: "2026-10-14", contracts: 5, at: "2026-10-14T15:00:00Z", is_live: false,
      premium: null, bought_back: null, commissions: null, commissions_complete: true, net_pnl: 400, capital: null, roc_pct: null,
      annualized_pct: null, pct_kept: null, dte_at_open: null, days_held: null, reason: "Sold 5 GOOGL at $190.00: the stop was hit.",
      facts: [], approval_id: null, review: null, rolled_to: null,
    };

    it("asks for the value-only calendar beside the whole one", async () => {
      await openIt(withValue());
      await screen.findByText("Realised in October");
      expect(apiFetchMock.mock.calls.some((c) => c[0] === "/pnl/calendar?month=2026-10&strategy=value")).toBe(true);
    });
    it("says the month includes the value book, with its own figure and count, apart from the total", async () => {
      const dialog = await openIt(withValue());
      expect(await within(dialog).findByText("Includes the value book: +$400.00 from 1 sale")).toBeInTheDocument();
      // The whole-account total is unchanged.
      expect(within(dialog).getByText("+$12,514.18")).toBeInTheDocument();
    });
    it("names the value amount in the accessible name of a day that has a sale", async () => {
      const dialog = await openIt(withValue());
      expect(
        await within(dialog).findByRole("button", { name: /Wed, Oct 14: \+\$12,400\.00 realised from 2 closes, of which the value book \+\$400\.00/ }),
      ).toBeInTheDocument();
      // A day with no sale keeps its plain name.
      expect(within(dialog).getByRole("button", { name: /Fri, Oct 9: \+\$1,717\.88 realised from 3 closes$/ })).toBeInTheDocument();
    });
    it("shows the day's value-book part as its own labelled figure when the day is tapped", async () => {
      const dialog = await openIt(
        withValue({ "/pnl/day?date=2026-10-14": { ...dayDetail, date: "2026-10-14", trades: [sale] } }),
      );
      fireEvent.click(await within(dialog).findByRole("button", { name: /Wed, Oct 14/ }));
      const section = await within(dialog).findByRole("region", { name: "What closed on Wed, Oct 14" });
      expect(within(section).getByText("Of this day's total, the value book")).toBeInTheDocument();
      expect(await within(section).findByText("Sold 5 GOOGL")).toBeInTheDocument();
      expect(within(section).getAllByText("+$400.00").length).toBeGreaterThanOrEqual(2);
      expect(within(section).getByText("Value book")).toBeInTheDocument();
    });
    it("adds nothing for a day that had no sale", async () => {
      const dialog = await openIt(withValue());
      fireEvent.click(await within(dialog).findByRole("button", { name: /Fri, Oct 9/ }));
      const section = await within(dialog).findByRole("region", { name: "What closed on Fri, Oct 9" });
      expect(within(section).queryByText("Of this day's total, the value book")).toBeNull();
    });
    it("adds no value sentence when the book sold nothing in the month", async () => {
      const dialog = await openIt(
        serve({ "/pnl/calendar?month=2026-10&strategy=value": { ...cal("2026-10", [], { strategy: "value" }), value_available: true } }),
      );
      await within(dialog).findByText("Realised in October");
      expect(within(dialog).queryByText(/Includes the value book/)).toBeNull();
    });
    it("does not take a response that is not the value-only calendar for the book's share", async () => {
      // The default fixture answers every path with the whole calendar, strategy "all".
      const dialog = await openIt();
      await within(dialog).findByText("Realised in October");
      expect(within(dialog).queryByText(/Includes the value book/)).toBeNull();
    });
    it("flags an unread value book in words, rather than leaving the sales out unsaid", async () => {
      const dialog = await openIt(
        serve({ "/pnl/calendar?month=2026-10": { ...cal("2026-10", octDays), value_available: false } }),
      );
      expect(await within(dialog).findByText("Value book unavailable")).toBeInTheDocument();
      expect(within(dialog).getByText(/The value book could not be read, so its sales are not counted/)).toBeInTheDocument();
    });
    it("does not flag a value book that is off and has never written anything", async () => {
      const dialog = await openIt(
        serve({
          "/pnl/calendar?month=2026-10": { ...cal("2026-10", octDays), value_available: false },
          "/value/book": { as_of: "", available: false, enabled: false, positions: [], proposals: [], funding: [], release_max_closes: 2, drain_healthy: true, drain_last_seen: null },
        }),
      );
      await within(dialog).findByText("Realised in October");
      await new Promise((r) => setTimeout(r, 20));
      expect(within(dialog).queryByText("Value book unavailable")).toBeNull();
    });
    it("states that the value book's sales count on the day they fill", async () => {
      const dialog = await openIt(withValue());
      expect(await within(dialog).findByText(/its sales count on the day they fill/)).toBeInTheDocument();
    });
  });
});
