import { fireEvent, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { RefreshControl } from "./RefreshControl";

const ISO = new Date().toISOString();

function pendingCommand(id: number) {
  return {
    id,
    kind: "refresh",
    status: "pending",
    result: null,
    needs_confirmation: false,
    confirm_token: null,
    created_at: ISO,
    applied_at: null,
    as_of: ISO,
    created: true,
  };
}

function terminalCommand(
  id: number,
  status: "applied" | "failed",
  result: Record<string, unknown> | null,
) {
  return {
    id,
    kind: "refresh",
    status,
    result,
    needs_confirmation: false,
    confirm_token: null,
    created_at: ISO,
    applied_at: ISO,
    as_of: ISO,
  };
}

describe("RefreshControl", () => {
  it("fires one POST /commands with kind refresh and renders CommandReceipt", async () => {
    renderWithQuery(<RefreshControl />, {
      "/commands": pendingCommand(101),
      "/commands/101": pendingCommand(101),
    });

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));

    await waitFor(() => {
      const postCalls = apiFetchMock.mock.calls.filter((c) => c[0] === "/commands");
      expect(postCalls.length).toBe(1);
    });
    const [, init] = apiFetchMock.mock.calls.find((c) => c[0] === "/commands") as [
      string,
      RequestInit,
    ];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ kind: "refresh", payload: {} });

    expect(await screen.findByTestId("command-receipt")).toBeInTheDocument();
  });

  it("renders a broker_unavailable failure as a plain answer, not red error chrome", async () => {
    renderWithQuery(<RefreshControl />, {
      "/commands": pendingCommand(102),
      "/commands/102": terminalCommand(102, "failed", { reason: "broker_unavailable" }),
    });

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));

    const receipt = await screen.findByTestId("command-receipt");
    await waitFor(() => expect(receipt.getAttribute("data-state")).toBe("answered"));
    expect(screen.getByText(/not connected/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Failed")).toBeNull();
  });

  it("invalidates the portfolio queries once the command goes terminal", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/commands") return pendingCommand(103);
      if (path === "/commands/103") {
        return terminalCommand(103, "applied", { captured_at: ISO, positions: 3, snapshot_id: 9 });
      }
      throw new Error(`unmocked path ${path}`);
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(["portfolio", "summary"], { placeholder: true });
    qc.setQueryData(["portfolio", "calendar", 45], { placeholder: true });
    render(
      <QueryClientProvider client={qc}>
        <RefreshControl />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));

    await waitFor(() => {
      expect(qc.getQueryState(["portfolio", "summary"])?.isInvalidated).toBe(true);
    });
    // The ["portfolio"] prefix catches every panel's key, including calendar's.
    expect(qc.getQueryState(["portfolio", "calendar", 45])?.isInvalidated).toBe(true);
  });

  it("polling stops at a terminal status: no further GET after the command is terminal", async () => {
    let getCalls = 0;
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/commands") return pendingCommand(104);
      if (path === "/commands/104") {
        getCalls += 1;
        return terminalCommand(104, "failed", { reason: "broker_unavailable" });
      }
      throw new Error(`unmocked path ${path}`);
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <RefreshControl />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));

    await waitFor(() => expect(getCalls).toBeGreaterThanOrEqual(1));
    await waitFor(() =>
      expect(screen.getByTestId("command-receipt").getAttribute("data-state")).toBe("answered"),
    );

    const callsAtTerminal = getCalls;
    // useCommandStatus polls every 2s while pending; wait well past that and
    // confirm no additional GET arrived once the status went terminal.
    await new Promise((resolve) => setTimeout(resolve, 2500));
    expect(getCalls).toBe(callsAtTerminal);
  }, 10000);

  it("disables the button while a command is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    apiFetchMock.mockImplementation(
      (path: string) =>
        new Promise((r) => {
          if (path === "/commands") resolve = r;
        }),
    );
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RefreshControl />
      </QueryClientProvider>,
    );

    const button = screen.getByRole("button", { name: /refresh/i }) as HTMLButtonElement;
    fireEvent.click(button);
    await waitFor(() => expect(button.disabled).toBe(true));
    resolve(pendingCommand(105));
  });
});
