import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ControlsStrip } from "./ControlsStrip";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const apiFetch = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return {
    ...(actual as object),
    apiFetch: (...args: unknown[]) => apiFetch(...args),
  };
});

const submitCommand = vi.fn();
vi.mock("@/lib/commands", async () => {
  const actual = await vi.importActual("@/lib/commands");
  return {
    ...(actual as object),
    submitCommand: (...args: unknown[]) => submitCommand(...args),
    confirmCommand: (...args: unknown[]) => vi.fn(),
  };
});

afterEach(cleanup);
afterEach(() => {
  apiFetch.mockReset();
  submitCommand.mockReset();
});

function controlsState(overrides: Record<string, unknown> = {}) {
  return {
    as_of: "2026-09-07T10:00:00Z",
    autonomy: { level: "observe", label: "Observe" },
    rungs: [
      { level: "observe", label: "Observe" },
      { level: "manual", label: "Manual" },
      { level: "whitelist", label: "Whitelist" },
      { level: "full", label: "Full" },
    ],
    halted: false,
    halt_reason: null,
    halted_at: null,
    mode: "paper",
    drain_healthy: true,
    drain_last_seen: "2026-09-07T09:59:00Z",
    pending_commands: 0,
    ...overrides,
  };
}

describe("ControlsStrip", () => {
  it("renders the pills read-only when healthy and not halted", async () => {
    apiFetch.mockResolvedValue(controlsState());
    withClient(<ControlsStrip />);

    await waitFor(() => expect(screen.getByText("paper")).toBeTruthy());
    const select = screen.getByTestId("autonomy-select") as HTMLSelectElement;
    expect(select.value).toBe("observe");
    expect(select.options).toHaveLength(4);
    expect(screen.queryByTestId("halted-banner")).toBeNull();
    expect(screen.queryByTestId("drain-dead-warning")).toBeNull();
  });

  it("the halted banner is present when halted is true, with reason and time as text", async () => {
    apiFetch.mockResolvedValue(
      controlsState({
        halted: true,
        halt_reason: "spread blew out",
        halted_at: "2026-09-07T09:41:00Z",
      }),
    );
    withClient(<ControlsStrip />);

    const banner = await screen.findByTestId("halted-banner");
    // Fill and text, not colour alone: the banner's own sentences carry the state.
    expect(banner.textContent).toContain("Execution is HALTED");
    expect(banner.textContent).toContain("spread blew out");
    expect(banner.textContent).toContain("No new orders will be queued or transmitted");
  });

  it("a halted state with no recorded time says so honestly, not with a fabricated one", async () => {
    apiFetch.mockResolvedValue(
      controlsState({ halted: true, halt_reason: "circuit breaker", halted_at: null }),
    );
    withClient(<ControlsStrip />);

    const banner = await screen.findByTestId("halted-banner");
    expect(banner.textContent).toContain("unknown time");
  });

  it("drain_healthy false renders the not-draining line beside the controls, immediately", async () => {
    apiFetch.mockResolvedValue(controlsState({ drain_healthy: false, drain_last_seen: null }));
    withClient(<ControlsStrip />);

    const warn = await screen.findByTestId("drain-dead-warning");
    expect(warn.textContent).toContain(
      "the trading service is not draining commands",
    );
    expect(warn.textContent).toContain("never run");
    // The pill states it in words too, not colour alone.
    expect(screen.getByText("unhealthy")).toBeTruthy();
  });

  it("the strip's controls still render when the drain is dead: a halt must be queueable", async () => {
    apiFetch.mockResolvedValue(controlsState({ drain_healthy: false }));
    withClient(<ControlsStrip />);

    await screen.findByTestId("drain-dead-warning");
    expect(screen.getByTestId("halt-button")).toBeTruthy();
    expect(screen.getByTestId("autonomy-select")).toBeTruthy();
  });
});