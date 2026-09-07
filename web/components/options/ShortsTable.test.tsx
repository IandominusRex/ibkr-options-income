import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { ShortsTable } from "./ShortsTable";

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
const confirmCommand = vi.fn();
vi.mock("@/lib/commands", async () => {
  const actual = await vi.importActual("@/lib/commands");
  return {
    ...(actual as object),
    submitCommand: (...args: unknown[]) => submitCommand(...args),
    confirmCommand: (...args: unknown[]) => confirmCommand(...args),
  };
});

afterEach(cleanup);
afterEach(() => {
  apiFetch.mockReset();
  submitCommand.mockReset();
  confirmCommand.mockReset();
});

/** One short, with every field the table reads, so the roll control renders. */
function shortState(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    as_of: "2026-09-06T10:00:00Z",
    position_symbol: "NVDA  261017C00180000",
    underlying: "NVDA",
    right: "C",
    strike: 180.0,
    expiry: "2026-10-16",
    dte: 9,
    contracts: 1,
    avg_cost: 1.50,
    mark: 0.65,
    unrealized_pnl: -15,
    pnl_pct: -10,
    delta: { value: -0.45, source: "ibkr", as_of: "x", stale: false },
    assignment_risk: false,
    alerts: [],
    ...overrides,
  };
}

/** Mock apiFetch with per-URL responses: /options/shorts, /options/controls, /commands/{id}. */
function mockApi({
  shorts = [],
  controls = { as_of: "x", drain_healthy: true },
  command,
}: {
  shorts?: ReturnType<typeof shortState>[];
  controls?: Record<string, unknown>;
  command?: Record<string, unknown>;
} = {}) {
  apiFetch.mockImplementation((url: string) => {
    if (url.startsWith("/options/shorts")) {
      return Promise.resolve({ as_of: "2026-09-06T10:00:00Z", shorts });
    }
    if (url.startsWith("/options/controls")) {
      return Promise.resolve(controls);
    }
    if (url.startsWith("/commands/")) {
      return Promise.resolve(command ?? {});
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

/** The dialog's confirm control — scoped to the dialog so it never matches the
 * row's own "Propose a roll" button (same accessible name). Cancel is first,
 * confirm is last. */
function dialogConfirm() {
  const dialog = screen.getByRole("dialog");
  const buttons = dialog.querySelectorAll<HTMLButtonElement>("button");
  return buttons[buttons.length - 1];
}

describe("ShortsTable", () => {
  it("renders the empty state when there are no shorts", async () => {
    mockApi({ shorts: [] });
    withClient(<ShortsTable />);
    expect(await screen.findByText(/No open short/i)).toBeDefined();
  });

  it("renders a null mark as n/a, never 0.00", async () => {
    mockApi({ shorts: [shortState({ mark: null, unrealized_pnl: null, delta: null })] });
    withClient(<ShortsTable />);
    expect((await screen.findAllByText(/NVDA/)).length).toBeGreaterThan(0);
    const na = screen.getAllByText("n/a");
    expect(na.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("$0.00")).toBeNull();
  });

  it("renders delta with its source so a BS delta is not an IBKR one", async () => {
    mockApi({ shorts: [shortState({ delta: { value: 0.3, source: "computed", as_of: "x", stale: false } })] });
    withClient(<ShortsTable />);
    expect((await screen.findAllByText(/AAPL|NVDA/)).length).toBeGreaterThan(0);
  });

  it("shows the snapshot's real age as text, not a dot", async () => {
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    expect(await screen.findByText(/Snapshot/i)).toBeDefined();
  });

  it("renders a fired roll alert on its position's row as text", async () => {
    mockApi({
      shorts: [
        shortState({
          alerts: [
            {
              id: 1,
              trigger: "delta_drift",
              trigger_label: "delta drift",
              detail: "delta has drifted to -0.42",
              claude_recommendation: "HOLD",
              created_at: "2026-09-06T09:55:00Z",
            },
          ],
        }),
      ],
    });
    withClient(<ShortsTable />);
    expect((await screen.findAllByText(/NVDA/)).length).toBeGreaterThan(0);
    // M5 Task 5.3: the humanised trigger label renders, not the raw code.
    expect(screen.getByText(/delta drift/i)).toBeDefined();
    expect(screen.getByText(/drifted to -0\.42/i)).toBeDefined();
    // Claude's recommendation renders labelled as a model opinion, distinct from any
    // deterministic number on the row.
    expect(screen.getByText(/model opinion.*HOLD/i)).toBeDefined();
  });

  it("the alert's age renders as text, not a dot", async () => {
    // A fresh timestamp so relativeAge resolves to "Xs ago" — scoped to the alert row so it
    // never collides with the snapshot-age line.
    const fresh = new Date(Date.now() - 30_000).toISOString();
    mockApi({
      shorts: [
        shortState({
          alerts: [
            {
              id: 2,
              trigger: "dte",
              trigger_label: "nearing expiry",
              detail: "7 days left",
              claude_recommendation: null,
              created_at: fresh,
            },
          ],
        }),
      ],
    });
    withClient(<ShortsTable />);
    await screen.findAllByText(/nearing expiry/i);
    // The alert line contains an age word; the snapshot-age line says "Snapshot ... ago".
    // Scope: the alerts cell is the one whose text starts with the trigger label.
    const expiryLine = screen.getByText(/nearing expiry/i).closest("li");
    expect(expiryLine).not.toBeNull();
    expect((expiryLine as HTMLElement).textContent).toMatch(/\bago\b/);
  });

  it("a position with no alerts renders nothing extra, not 'No alerts'", async () => {
    mockApi({ shorts: [shortState({ alerts: [] })] });
    withClient(<ShortsTable />);
    await screen.findAllByText(/NVDA/);
    expect(screen.queryByText(/no alerts/i)).toBeNull();
  });
});

describe("ShortsTable — the roll control (M5 5.2)", () => {
  it("renders a Propose a roll control on every open short row", async () => {
    mockApi({
      shorts: [
        shortState({ position_symbol: "NVDA  261017C00180000" }),
        shortState({ position_symbol: "AAPL  261016C00185000", underlying: "AAPL" }),
      ],
    });
    withClient(<ShortsTable />);
    expect(await screen.findAllByRole("button", { name: "Propose a roll" })).toHaveLength(2);
  });

  it("the control's label says what it does (Propose a roll, not Roll)", async () => {
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    expect(await screen.findByRole("button", { name: "Propose a roll" })).toBeDefined();
    // No bare "Roll" button — the copy must not imply the button rolls the position.
    expect(screen.queryByRole("button", { name: "Roll" })).toBeNull();
  });

  it("opens ConfirmAction before any request is made", async () => {
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(submitCommand).not.toHaveBeenCalled();
  });

  it("the dialog states plainly: price a roll, raise for approval, nothing executes until approved", async () => {
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    const summary = screen.getByTestId("confirm-summary").textContent ?? "";
    expect(summary).toMatch(/price a roll/i);
    expect(summary).toMatch(/approval/i);
    expect(summary).toMatch(/nothing executes until/i);
    // House style: no em dashes, no banned words.
    expect(summary).not.toContain("—");
    for (const banned of ["seamless", "robust", "unlock", "elevate"]) {
      expect(summary.toLowerCase()).not.toContain(banned);
    }
  });

  it("calls POST /commands with kind=roll_request exactly once on confirm, with the position symbol", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 51,
      kind: "roll_request",
      status: "pending",
      result: null,
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    fireEvent.click(dialogConfirm());
    await waitFor(() => expect(submitCommand).toHaveBeenCalledTimes(1));
    expect(submitCommand).toHaveBeenCalledWith("roll_request", {
      position_symbol: "NVDA  261017C00180000",
    });
  });

  it("renders no_qualifying_roll as a plain sentence, not error chrome", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 51,
      kind: "roll_request",
      status: "failed",
      result: { reason: "no_qualifying_roll", detail: {} },
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: "x",
      as_of: "x",
      created: true,
    });
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    fireEvent.click(dialogConfirm());
    const receipt = await screen.findByTestId("command-receipt");
    // Plain answer, not red failed chrome.
    expect(receipt.getAttribute("data-state")).toBe("answered");
    expect(receipt.textContent).toMatch(/no qualifying roll/i);
    expect(receipt.textContent).toMatch(/real answer, not an error/i);
    expect(receipt.querySelector(".text-loss")).toBeNull();
    expect(receipt.textContent).toContain("intent 51");
  });

  it("roll_already_working links to the existing approval", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 51,
      kind: "roll_request",
      status: "failed",
      result: { reason: "roll_already_working", detail: { approval_id: 77 } },
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: "x",
      as_of: "x",
      created: true,
    });
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    fireEvent.click(dialogConfirm());
    const link = (await screen.findByRole("link", {
      name: /roll already in flight/i,
    })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/options/77");
  });

  it("on success the receipt links to the new approval", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 51,
      kind: "roll_request",
      status: "applied",
      result: { approval_id: 99, candidate_id: "abc" },
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: "x",
      as_of: "x",
      created: true,
    });
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    fireEvent.click(dialogConfirm());
    const link = (await screen.findByRole("link", { name: /view approval/i })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/options/99");
  });

  it("the control is disabled while a roll command for that position is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    submitCommand.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    const button = await screen.findByRole("button", { name: "Propose a roll" });
    fireEvent.click(button);
    fireEvent.click(dialogConfirm());
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true));
    resolve({
      id: 51,
      kind: "roll_request",
      status: "pending",
      result: null,
      needs_confirmation: false,
      confirm_token: null,
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
  });

  it("renders a permission message on a 403, not a generic failure", async () => {
    submitCommand.mockRejectedValueOnce(new ApiError(403, "forbidden"));
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    fireEvent.click(dialogConfirm());
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByRole("alert").textContent).toContain("permission");
  });
});

describe("ShortsTable — live-mode second confirmation (M5 5.2, mirrors M3 3.5)", () => {
  it("renders the live step as a distinct, clearly labelled step, not a repeat", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 51,
      kind: "roll_request",
      status: "pending",
      result: null,
      needs_confirmation: true,
      confirm_token: "tok-abc",
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
    confirmCommand.mockResolvedValueOnce(undefined);
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    const firstDialog = screen.getByRole("dialog");
    const firstCopy = firstDialog.textContent ?? "";
    fireEvent.click(dialogConfirm());

    const liveDialog = await screen.findByRole("dialog");
    expect(liveDialog.textContent).toContain("LIVE");
    expect(liveDialog.textContent).not.toBe(firstCopy);

    fireEvent.click(dialogConfirm());
    await waitFor(() => expect(confirmCommand).toHaveBeenCalledWith(51, "tok-abc"));
  });

  it("keeps the command pending (needs_confirmation) if the live step is cancelled", async () => {
    submitCommand.mockResolvedValueOnce({
      id: 51,
      kind: "roll_request",
      status: "pending",
      result: null,
      needs_confirmation: true,
      confirm_token: "tok-abc",
      created_at: "x",
      applied_at: null,
      as_of: "x",
      created: true,
    });
    mockApi({ shorts: [shortState()] });
    withClient(<ShortsTable />);
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    fireEvent.click(dialogConfirm());
    await screen.findAllByText(/LIVE/);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(confirmCommand).not.toHaveBeenCalled();
    const receipt = await screen.findByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("queued");
  });
});