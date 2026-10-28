import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock } from "@/lib/test-query";
import { RefreshButton } from "./RefreshButton";

const ISO = new Date().toISOString();
const controls = (over: Record<string, unknown> = {}) => ({
  as_of: ISO, autonomy: { level: "manual", label: "Manual" }, rungs: [], halted: false, halt_reason: null,
  mode: "paper", drain_healthy: true, drain_last_seen: null, pending_commands: 0, ...over,
});
const command = (id: number, status: string, result: Record<string, unknown> | null = null) => ({
  id, kind: "refresh", status, result, needs_confirmation: false, confirm_token: null,
  created_at: ISO, applied_at: status === "pending" ? null : ISO, as_of: ISO, created: true,
});

function mount(ui = <RefreshButton scope="broker" />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
  return qc;
}

describe("RefreshButton", () => {
  it("is an icon button with an accessible name, never lime", () => {
    mount(<RefreshButton label="Refresh trades" />);
    const button = screen.getByRole("button", { name: "Refresh trades" });
    expect(button.className).not.toMatch(/bg-primary/);
  });

  it("on a page scope sends nothing and asks for every query again", async () => {
    apiFetchMock.mockImplementation(async () => {
      throw new Error("a page refresh must not call the API by itself");
    });
    const qc = mount(<RefreshButton scope="page" />);
    qc.setQueryData(["news", "feed"], { placeholder: true });
    qc.setQueryData(["analysis", "AAPL"], { placeholder: true });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(qc.getQueryState(["news", "feed"])?.isInvalidated).toBe(true));
    expect(qc.getQueryState(["analysis", "AAPL"])?.isInvalidated).toBe(true);
    expect(apiFetchMock.mock.calls.filter((c) => c[0] === "/commands")).toHaveLength(0);
  });

  it("on a broker scope sends one refresh command, then asks for every query again", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/commands") return command(201, "pending");
      if (path === "/commands/201") return command(201, "applied", { positions: 3 });
      if (path === "/options/controls") return controls();
      throw new Error(`unmocked ${path}`);
    });
    const qc = mount(<RefreshButton scope="broker" />);
    qc.setQueryData(["position", "AAPL", "shares"], { placeholder: true });
    qc.setQueryData(["portfolio", "value", "1m"], { placeholder: true });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(qc.getQueryState(["position", "AAPL", "shares"])?.isInvalidated).toBe(true));
    expect(qc.getQueryState(["portfolio", "value", "1m"])?.isInvalidated).toBe(true);
    const posts = apiFetchMock.mock.calls.filter((c) => c[0] === "/commands");
    expect(posts).toHaveLength(1);
    expect(JSON.parse((posts[0][1] as RequestInit).body as string)).toEqual({ kind: "refresh", payload: {} });
    // A refresh that worked says nothing.
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("is busy and disabled while the command is in flight", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/commands") return command(202, "pending");
      if (path === "/commands/202") return command(202, "pending");
      if (path === "/options/controls") return controls();
      throw new Error(`unmocked ${path}`);
    });
    mount();
    const button = screen.getByRole("button", { name: "Refresh" });
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("says in words that the broker is not connected, and that the figures are the last reading", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/commands") return command(203, "pending");
      if (path === "/commands/203") return command(203, "failed", { reason: "broker_unavailable" });
      if (path === "/options/controls") return controls();
      throw new Error(`unmocked ${path}`);
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("The broker is not connected. These figures are the last reading.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
  });

  it("says the trading service is not draining commands when it is not", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/commands") return command(204, "pending");
      if (path === "/commands/204") return command(204, "pending");
      if (path === "/options/controls") return controls({ drain_healthy: false });
      throw new Error(`unmocked ${path}`);
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("The trading service is not draining commands.")).toBeInTheDocument();
  });

  it("says nothing was sent when the command could not be created", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/options/controls") return controls();
      throw new Error("down");
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The command could not be created. Nothing was sent.");
  });
});
