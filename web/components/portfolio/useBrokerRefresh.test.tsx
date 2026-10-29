import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock } from "@/lib/test-query";
import { useBrokerRefresh } from "./useBrokerRefresh";

const ISO = new Date().toISOString();

// GET /commands/{id} builds its CommandStatus without `as_of`, so the API model stamps a fresh one on
// every response: no two bodies are ever equal, and TanStack's structural sharing cannot hand back the
// old object. The mock reproduces that.
let stamp = 0;
const freshAsOf = () => new Date(Date.UTC(2026, 9, 30, 12, 0, stamp++)).toISOString();

function command(id: number, status: string, result: Record<string, unknown> | null = null) {
  return {
    id, kind: "refresh", status, result, needs_confirmation: false, confirm_token: null,
    created_at: ISO, applied_at: status === "pending" ? null : ISO, as_of: freshAsOf(), created: true,
  };
}

const counts = { commandGets: 0, probe: 0, controls: 0 };
let nextId = 300;

function mockApi() {
  counts.commandGets = 0;
  counts.probe = 0;
  counts.controls = 0;
  nextId = 300;
  stamp = 0;
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === "/commands") return command(++nextId, "pending");
    if (path.startsWith("/commands/")) {
      counts.commandGets += 1;
      return command(Number(path.slice("/commands/".length)), "applied", { positions: 3 });
    }
    if (path === "/options/controls") {
      counts.controls += 1;
      return {
        as_of: ISO, autonomy: { level: "manual", label: "Manual" }, rungs: [], halted: false, halt_reason: null,
        mode: "paper", drain_healthy: true, drain_last_seen: null, pending_commands: 0,
      };
    }
    throw new Error(`unmocked ${path}`);
  });
}

// An unrelated active query on the page, counting how often it is asked for again.
function Harness({ scope }: { scope: "portfolio" | "all" }) {
  const { refresh, inFlight, current } = useBrokerRefresh(scope);
  useQuery({
    queryKey: ["probe", "chart"],
    queryFn: async () => ({ fetches: ++counts.probe }),
  });
  return (
    <button type="button" disabled={inFlight} onClick={refresh}>
      Go {current?.status ?? "idle"}
    </button>
  );
}

function mount(scope: "portfolio" | "all") {
  mockApi();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Harness scope={scope} />
    </QueryClientProvider>,
  );
  return qc;
}

// A fixed real-time window, never "until the loop ends": the unfixed hook has no end.
const settle = (ms = 400) => act(() => new Promise<void>((r) => setTimeout(r, ms)));

describe("useBrokerRefresh", () => {
  it("asks for the page's queries once per finished command, not once per poll body", async () => {
    mount("all");
    await waitFor(() => expect(counts.probe).toBe(1));
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("applied"));
    await settle();

    // One poll for the terminal status; the command's own query is not part of the invalidation.
    expect(counts.commandGets).toBeLessThanOrEqual(2);
    // The mount fetch plus exactly one refetch from the single invalidation.
    expect(counts.probe).toBeGreaterThanOrEqual(2);
    expect(counts.probe).toBeLessThanOrEqual(2);
    expect(counts.controls).toBeLessThanOrEqual(2);
  });

  it("a second refresh (a new command id) invalidates again", async () => {
    mount("all");
    await waitFor(() => expect(counts.probe).toBe(1));
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("applied"));
    await settle();
    const afterFirst = counts.probe;
    expect(afterFirst).toBeLessThanOrEqual(2);

    await waitFor(() => expect(screen.getByRole("button")).toBeEnabled());
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(counts.probe).toBeGreaterThan(afterFirst));
    await settle();

    expect(counts.probe).toBe(afterFirst + 1);
    expect(counts.commandGets).toBeLessThanOrEqual(4);
  });

  it("scope portfolio leaves queries outside the portfolio prefix alone", async () => {
    const qc = mount("portfolio");
    qc.setQueryData(["portfolio", "summary"], { placeholder: true });
    await waitFor(() => expect(counts.probe).toBe(1));
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(qc.getQueryState(["portfolio", "summary"])?.isInvalidated).toBe(true));
    await settle(150);
    expect(counts.probe).toBe(1);
  });
});
