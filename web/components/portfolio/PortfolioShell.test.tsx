import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { PortfolioShell } from "./PortfolioShell";

function summaryResponse() {
  return {
    source: "monitor",
    degraded: false,
    account: null,
    exposure: null,
    note: null,
    as_of: new Date().toISOString(),
  };
}

// Task 3.3 wired PositionsPanel into the Positions tab, which self-fetches
// GET /portfolio/positions - every render of <PortfolioShell/> now needs this
// mocked too, since Positions is the default active tab.
function positionsResponse() {
  return { as_of: new Date().toISOString(), source: "monitor", degraded: false, groups: [] };
}

// Task 3.4 wired CampaignsPanel into the Campaigns tab, which self-fetches
// GET /portfolio/campaigns - mounting that tab now needs this mocked too.
function campaignsResponse() {
  return { as_of: new Date().toISOString(), campaigns: [] };
}

// Task 3.5 wired CalendarPanel into the Calendar tab, which self-fetches
// GET /portfolio/calendar - mounting that tab now needs this mocked too.
function calendarResponse() {
  return {
    as_of: new Date().toISOString(),
    source: "monitor",
    degraded: false,
    horizon_days: 45,
    days: [],
  };
}

// Not named in the task brief's Files list (SummaryPanel.test.tsx and
// DegradedNotice.test.tsx were), but "the tab bar renders three tabs and
// switching does not refetch the summary" is one of the brief's required,
// each-with-a-test behaviours and nothing else in the plan tests it - so it
// lands here, next to the component it exercises.
describe("PortfolioShell", () => {
  it("renders three tabs: Positions, Campaigns, Calendar", async () => {
    renderWithQuery(<PortfolioShell />, {
      "/portfolio/summary": summaryResponse(),
      "/portfolio/positions": positionsResponse(),
      "/portfolio/campaigns": campaignsResponse(),
      "/portfolio/calendar": calendarResponse(),
    });
    expect(await screen.findByRole("button", { name: "Positions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Campaigns" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Calendar" })).toBeInTheDocument();
  });

  it("switching tabs does not refetch the summary", async () => {
    renderWithQuery(<PortfolioShell />, {
      "/portfolio/summary": summaryResponse(),
      "/portfolio/positions": positionsResponse(),
      "/portfolio/campaigns": campaignsResponse(),
      "/portfolio/calendar": calendarResponse(),
    });
    await screen.findByRole("button", { name: "Positions" });

    const callsToSummary = () =>
      apiFetchMock.mock.calls.filter((call) => call[0] === "/portfolio/summary").length;
    const before = callsToSummary();

    fireEvent.click(screen.getByRole("button", { name: "Campaigns" }));
    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    fireEvent.click(screen.getByRole("button", { name: "Positions" }));

    expect(callsToSummary()).toBe(before);
  });

  it("switching tabs changes the panel content below the summary", async () => {
    renderWithQuery(<PortfolioShell />, {
      "/portfolio/summary": summaryResponse(),
      "/portfolio/positions": positionsResponse(),
      "/portfolio/campaigns": campaignsResponse(),
      "/portfolio/calendar": calendarResponse(),
    });
    await screen.findByRole("button", { name: "Positions" });
    // Task 3.3: the Positions tab now renders the real PositionsPanel, not
    // placeholder text - an empty, captured account reads "No open positions."
    // through role="status".
    expect(await screen.findByRole("status")).toHaveTextContent(/no open positions/i);

    fireEvent.click(screen.getByRole("button", { name: "Campaigns" }));
    // Task 3.4: the Campaigns tab now renders the real CampaignsPanel, not
    // placeholder text - an empty response reads through EmptyState (no
    // role="status", unlike PositionsPanel's empty rung).
    expect(await screen.findByText(/no campaigns/i)).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    // Task 3.5: the Calendar tab now renders the real CalendarPanel, not
    // placeholder text.
    expect(await screen.findByText(/no option expiries/i)).toBeInTheDocument();
  });

  it("mounts the refresh control in the header, visible regardless of the active tab", async () => {
    renderWithQuery(<PortfolioShell />, {
      "/portfolio/summary": summaryResponse(),
      "/portfolio/positions": positionsResponse(),
      "/portfolio/campaigns": campaignsResponse(),
      "/portfolio/calendar": calendarResponse(),
    });
    await screen.findByRole("button", { name: "Positions" });
    expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument();
  });
});
