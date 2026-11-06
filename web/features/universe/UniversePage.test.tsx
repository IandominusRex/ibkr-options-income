import { screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { UniversePage } from "./UniversePage";

const entry = (symbol: string) => ({ symbol, overridden: false, removed: false, created_by: null, created_at: null });

const universe = {
  as_of: "x",
  lists: [
    { name: "indexes", overridable: false, entries: [entry("SPY")] },
    { name: "watchlist", overridable: true, entries: [entry("PLTR")] },
    { name: "would_own", overridable: true, entries: [entry("NVDA"), entry("KO")] },
    { name: "actively_wheeling", overridable: false, entries: [entry("NVDA")] },
  ],
  sectors: { NVDA: "Semis" },
  strike_bands: {},
  editable: true,
};

const controls = {
  as_of: "", autonomy: { level: "approve", label: "Approve each trade" }, rungs: [], halted: false,
  halt_reason: null, halted_at: null, mode: "paper", drain_healthy: true, drain_last_seen: null, pending_commands: 0,
};

describe("UniversePage", () => {
  it("leads back to Research, then the title and what can be changed here", async () => {
    renderWithQuery(<UniversePage />, { "/universe": universe, "/options/controls": controls });
    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("href", "/research");
    expect(screen.getByRole("heading", { level: 1, name: "Universe" })).toBeInTheDocument();
    expect(screen.getByText(/Would own and Watchlist take add and remove here/)).toBeInTheDocument();
  });

  it("draws one card per list, in the API's order, with each list's count", async () => {
    renderWithQuery(<UniversePage />, { "/universe": universe, "/options/controls": controls });
    await screen.findByRole("heading", { level: 2, name: "Indexes" });
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Indexes",
      "Watchlist",
      "Would own",
      "Actively wheeling",
    ]);
    expect(screen.getAllByText("2 names")).toHaveLength(1);
    expect(screen.getByTestId("wheeling-tag-NVDA")).toHaveTextContent("Wheeling");
    expect(screen.getByTestId("dip-watch-tag-KO")).toHaveTextContent("Dip-watch");
  });

  it("holds its place while loading, and says a failed read in words", async () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = render(
      <QueryClientProvider client={qc}>
        <UniversePage />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("status", { name: "Loading the universe" })).toBeInTheDocument();
    first.unmount();
    apiFetchMock.mockImplementation(async () => {
      throw new Error("down");
    });
    const qc2 = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc2}>
        <UniversePage />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("The universe could not be loaded right now.")).toBeInTheDocument();
  });
});
