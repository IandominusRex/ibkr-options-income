import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { SectorGrid } from "./SectorGrid";

const sector = (name: string, iv: number | null) => ({
  sector: name, count: 2, change_pct: 0.5, best: { symbol: "A", change_pct: 1 }, worst: { symbol: "B", change_pct: 0 },
  avg_iv_rank: iv, iv_rank_count: iv == null ? 0 : 2,
});

describe("SectorGrid", () => {
  it("is one card, Sectors by IV rank, with a row per sector in the API's order", async () => {
    renderWithQuery(<SectorGrid />, { "/research/sectors": { as_of: "x", sectors: [sector("Semis", 70), sector("Banks", 30), sector("Bonds", null)] } });
    expect(screen.getByRole("heading", { level: 2, name: "Sectors by IV rank" })).toBeInTheDocument();
    await screen.findByText("Semis");
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Semis", "Banks", "Bonds"]);
  });

  it("holds its place while loading, and says an empty or failed read in words", async () => {
    apiFetchMock.mockImplementation(() => new Promise(() => {}));
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    const { render } = await import("@testing-library/react");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = render(
      <QueryClientProvider client={qc}>
        <SectorGrid />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("status", { name: "Loading the sectors" })).toBeInTheDocument();
    first.unmount();

    const empty = renderWithQuery(<SectorGrid />, { "/research/sectors": { as_of: "x", sectors: [] } });
    expect(await screen.findByText("No sector data yet.")).toBeInTheDocument();
    empty.unmount();

    apiFetchMock.mockImplementation(async () => {
      throw new Error("down");
    });
    const qc2 = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc2}>
        <SectorGrid />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("The sectors could not be loaded right now.")).toBeInTheDocument();
  });
});
