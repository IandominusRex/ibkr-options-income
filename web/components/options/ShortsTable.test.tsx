import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ShortsTable } from "./ShortsTable";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("ShortsTable", () => {
  it("renders the empty state when there are no shorts", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", shorts: [] });
    withClient(<ShortsTable />);
    expect(await screen.findByText(/No open short/i)).toBeDefined();
  });

  it("renders a null mark as n/a, never 0.00", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "2026-09-06T10:00:00Z",
      shorts: [
        {
          as_of: "2026-09-06T10:00:00Z",
          position_symbol: "NVDA P",
          underlying: "NVDA",
          right: "P",
          strike: 190.0,
          expiry: "2026-10-16",
          dte: 40,
          contracts: 1,
          avg_cost: 3.25,
          mark: null,
          unrealized_pnl: null,
          pnl_pct: null,
          delta: null,
          assignment_risk: false,
          alerts: [],
        },
      ],
    });
    withClient(<ShortsTable />);
    expect((await screen.findAllByText(/NVDA/)).length).toBeGreaterThan(0);
    const na = screen.getAllByText("n/a");
    expect(na.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("$0.00")).toBeNull();
  });

  it("renders delta with its source so a BS delta is not an IBKR one", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "2026-09-06T10:00:00Z",
      shorts: [
        {
          as_of: "2026-09-06T10:00:00Z",
          position_symbol: "AAPL C",
          underlying: "AAPL",
          right: "C",
          strike: 185.0,
          expiry: "2026-10-16",
          dte: 40,
          contracts: 1,
          avg_cost: 2.5,
          mark: 2.1,
          unrealized_pnl: 40,
          pnl_pct: 16,
          delta: { value: 0.3, source: "computed", as_of: "x", stale: false },
          assignment_risk: false,
          alerts: [],
        },
      ],
    });
    withClient(<ShortsTable />);
    expect((await screen.findAllByText(/AAPL/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/computed/)).toBeDefined();
  });

  it("shows the snapshot's real age as text, not a dot", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "2026-09-06T10:00:00Z",
      shorts: [
        {
          as_of: "2026-09-06T10:00:00Z",
          position_symbol: "NVDA P",
          underlying: "NVDA",
          right: "P",
          strike: 190.0,
          expiry: "2026-10-16",
          dte: 40,
          contracts: 1,
          avg_cost: 3.25,
          mark: 2.1,
          unrealized_pnl: 115,
          pnl_pct: 35,
          delta: null,
          assignment_risk: false,
          alerts: [],
        },
      ],
    });
    withClient(<ShortsTable />);
    expect(await screen.findByText(/Snapshot/i)).toBeDefined();
  });

  it("renders a fired roll alert on its position's row as text", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "2026-09-06T10:00:00Z",
      shorts: [
        {
          as_of: "2026-09-06T10:00:00Z",
          position_symbol: "NVDA P",
          underlying: "NVDA",
          right: "P",
          strike: 190.0,
          expiry: "2026-10-16",
          dte: 40,
          contracts: 1,
          avg_cost: 3.25,
          mark: 2.1,
          unrealized_pnl: 115,
          pnl_pct: 35,
          delta: null,
          assignment_risk: false,
          alerts: [
            {
              id: 1,
              trigger: "delta_drift",
              detail: "delta has drifted to -0.42",
              created_at: "x",
            },
          ],
        },
      ],
    });
    withClient(<ShortsTable />);
    expect((await screen.findAllByText(/NVDA/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/drifted to -0\.42/i)).toBeDefined();
  });

  it("asserts no roll button exists", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({ as_of: "x", shorts: [] });
    withClient(<ShortsTable />);
    await screen.findByText(/No open short/i);
    expect(screen.queryAllByRole("button", { name: /roll/i })).toHaveLength(0);
  });
});