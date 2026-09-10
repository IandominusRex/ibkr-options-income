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

// Not named in the task brief's Files list (SummaryPanel.test.tsx and
// DegradedNotice.test.tsx were), but "the tab bar renders three tabs and
// switching does not refetch the summary" is one of the brief's required,
// each-with-a-test behaviours and nothing else in the plan tests it - so it
// lands here, next to the component it exercises.
describe("PortfolioShell", () => {
  it("renders three tabs: Positions, Campaigns, Calendar", async () => {
    renderWithQuery(<PortfolioShell />, { "/portfolio/summary": summaryResponse() });
    expect(await screen.findByRole("button", { name: "Positions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Campaigns" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Calendar" })).toBeInTheDocument();
  });

  it("switching tabs does not refetch the summary", async () => {
    renderWithQuery(<PortfolioShell />, { "/portfolio/summary": summaryResponse() });
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
    renderWithQuery(<PortfolioShell />, { "/portfolio/summary": summaryResponse() });
    await screen.findByRole("button", { name: "Positions" });
    expect(screen.getByText(/Positions - coming/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Campaigns" }));
    expect(screen.getByText(/Campaigns - coming/i)).toBeInTheDocument();
    expect(screen.queryByText(/Positions - coming/i)).toBeNull();
  });
});
