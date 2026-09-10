import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { CalendarPanel } from "./CalendarPanel";
import type { CalendarDay, CalendarEntry, CalendarResponse } from "./types";

const ISO = new Date().toISOString();

function anEntry(overrides: Partial<CalendarEntry> = {}): CalendarEntry {
  return {
    as_of: ISO,
    symbol: "AAPL   260919C00230000",
    underlying: "AAPL",
    right: "C",
    strike: 230,
    contracts: 1,
    short: true,
    moneyness: "otm",
    consequence: "expires_worthless",
    assignment_risk: false,
    ...overrides,
  };
}

function aDay(expiry: string, dte: number, entries: CalendarEntry[]): CalendarDay {
  return { as_of: ISO, expiry, dte, entries };
}

function calendarResponse(
  days: CalendarDay[],
  overrides: Partial<CalendarResponse> = {},
): CalendarResponse {
  return { as_of: ISO, source: "monitor", degraded: false, horizon_days: 45, days, ...overrides };
}

describe("CalendarPanel", () => {
  it("renders days nearest first, each with its date and DTE", async () => {
    const near = aDay("2026-09-19", 9, [anEntry({ symbol: "s1" })]);
    const far = aDay("2026-10-17", 37, [anEntry({ symbol: "s2" })]);
    renderWithQuery(<CalendarPanel />, {
      "/portfolio/calendar": calendarResponse([near, far]),
    });

    const days = await screen.findAllByTestId("calendar-day");
    expect(days).toHaveLength(2);
    expect(days[0].textContent).toContain("9 DTE");
    expect(days[0].textContent).toMatch(/sep/i);
    expect(days[1].textContent).toContain("37 DTE");
    expect(days[1].textContent).toMatch(/oct/i);
  });

  it("renders an unknown consequence distinctly from expires-worthless", async () => {
    const day = aDay("2026-09-19", 9, [
      anEntry({ symbol: "s1", consequence: "unknown", moneyness: null }),
      anEntry({ symbol: "s2", consequence: "expires_worthless" }),
    ]);
    renderWithQuery(<CalendarPanel />, { "/portfolio/calendar": calendarResponse([day]) });

    const texts = (await screen.findAllByTestId("consequence")).map((n) => n.textContent);
    expect(new Set(texts).size).toBe(2);
  });

  it("renders called_away and assigned as distinct wordings", async () => {
    const day = aDay("2026-09-19", 9, [
      anEntry({ symbol: "s1", consequence: "assigned", right: "P", moneyness: "itm" }),
      anEntry({ symbol: "s2", consequence: "called_away", right: "C", moneyness: "itm" }),
    ]);
    renderWithQuery(<CalendarPanel />, { "/portfolio/calendar": calendarResponse([day]) });

    const texts = (await screen.findAllByTestId("consequence")).map((n) => n.textContent ?? "");
    expect(new Set(texts).size).toBe(2);
    expect(texts.some((t) => /assigned/i.test(t))).toBe(true);
    expect(texts.some((t) => /called away/i.test(t))).toBe(true);
  });

  it("the horizon control changes the query parameter", async () => {
    renderWithQuery(<CalendarPanel />, {
      "/portfolio/calendar": calendarResponse([]),
    });
    await screen.findByTestId("calendar-panel");
    const before = apiFetchMock.mock.calls.length;

    fireEvent.change(screen.getByLabelText(/horizon/i), { target: { value: "90" } });

    await waitFor(() => expect(apiFetchMock.mock.calls.length).toBeGreaterThan(before));
    const lastCall = apiFetchMock.mock.calls.at(-1)?.[0];
    expect(lastCall).toContain("/portfolio/calendar");
    expect(lastCall).toContain("horizon_days=90");
  });

  it("renders the freshness label above the content when days are present", async () => {
    const day = aDay("2026-09-19", 9, [anEntry()]);
    renderWithQuery(<CalendarPanel />, { "/portfolio/calendar": calendarResponse([day]) });
    await screen.findByTestId("calendar-day");
    // FreshnessLabel renders "just now" for a fresh as_of - proves it is really
    // mounted, not just imported.
    expect(screen.getByText(/just now/i)).toBeInTheDocument();
  });

  it("renders the freshness label above the content when there are no days too", async () => {
    renderWithQuery(<CalendarPanel />, { "/portfolio/calendar": calendarResponse([]) });
    await screen.findByTestId("calendar-panel");
    expect(screen.getByText(/just now/i)).toBeInTheDocument();
  });

  it("distinguishes no captured snapshot from no expiries within the horizon", async () => {
    renderWithQuery(<CalendarPanel />, {
      "/portfolio/calendar": calendarResponse([], { source: "none", degraded: true }),
    });
    expect(await screen.findByText(/no portfolio snapshot/i)).toBeInTheDocument();
  });

  it("renders no expiries within the horizon distinctly from no captured snapshot", async () => {
    renderWithQuery(<CalendarPanel />, {
      "/portfolio/calendar": calendarResponse([], { source: "monitor" }),
    });
    expect(await screen.findByText(/no option expiries/i)).toBeInTheDocument();
    expect(screen.queryByText(/no portfolio snapshot/i)).toBeNull();
  });
});
