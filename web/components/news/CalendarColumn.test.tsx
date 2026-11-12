import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { CalendarColumn } from "./CalendarColumn";

const ISO = "2026-11-07T01:00:00Z";
const econ = (title: string, actual: string | null, forecast: string | null) => ({
  title, scheduled_at: "2026-11-10T13:30:00Z", impact: "high", forecast, previous: null, actual, surprise_dir: null,
});
const earn = (symbol: string, held: boolean) => ({
  symbol, report_date: "2026-11-12", timing: "amc", eps_est: null, eps_actual: null, status: "scheduled", held,
});

describe("CalendarColumn", () => {
  it("is one card titled This week, with the releases and the earnings as rows", async () => {
    renderWithQuery(<CalendarColumn />, {
      "/news/calendar?days=7": { as_of: ISO, available: true, econ: [econ("CPI m/m", "0.4%", "0.3%")], earnings: [earn("NVDA", true)] },
    });
    expect(await screen.findByText("CPI m/m")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "This week" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Economic releases" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Earnings" })).toBeInTheDocument();
    expect(screen.getByText("0.4%").closest("li")).toHaveTextContent("0.4% vs 0.3% forecast");
    expect(screen.getByRole("link", { name: "NVDA" })).toHaveAttribute("href", "/news/NVDA");
    expect(screen.getByText("Held")).toHaveAttribute("data-tone", "neutral");
    expect(screen.getByRole("link", { name: "NVDA" }).closest("li")).toHaveTextContent("AMC");
  });

  it("hatches a missing forecast instead of printing nothing", async () => {
    renderWithQuery(<CalendarColumn />, {
      "/news/calendar?days=7": { as_of: ISO, available: true, econ: [econ("Retail sales", "1.1%", null)], earnings: [] },
    });
    const row = (await screen.findByText("Retail sales")).closest("li")!;
    expect(row.querySelector(".hatch")).toHaveTextContent("n/a");
  });

  it("says an empty week in words instead of vanishing", async () => {
    renderWithQuery(<CalendarColumn />, { "/news/calendar?days=7": { as_of: ISO, available: true, econ: [], earnings: [] } });
    expect(await screen.findAllByText("None in the next 7 days.")).toHaveLength(2);
  });

  it("says when the calendar has not been written, or could not be read", async () => {
    const { unmount } = renderWithQuery(<CalendarColumn />, {
      "/news/calendar?days=7": { as_of: ISO, available: false, econ: [], earnings: [] },
    });
    expect(await screen.findByText("The news service has not written the calendar yet.")).toBeInTheDocument();
    unmount();
    renderWithQuery(<CalendarColumn />, {});
    expect(await screen.findByText("The calendar could not be loaded.")).toBeInTheDocument();
  });
});
