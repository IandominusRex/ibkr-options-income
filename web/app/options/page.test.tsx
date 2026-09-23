import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import OptionsPage from "./page";

afterEach(cleanup);
afterEach(() => {
  submitCommand.mockReset();
  lastCommand = null;
});

// The tab bar and the Approvals/Submitted split are the thing under test.
// The other tabs' content is real elsewhere (ApprovalsList.test.tsx,
// AssessedBrowser.test.tsx, etc.) — stub them here so this test only pays
// for the network calls the Approvals/Submitted view actually needs.
vi.mock("@/components/options/ControlsStrip", () => ({
  ControlsStrip: () => null,
}));
vi.mock("@/components/options/AssessedBrowser", () => ({
  AssessedBrowser: () => <div>assessed stub</div>,
}));
vi.mock("@/components/options/OrdersTable", () => ({ OrdersTable: () => <div>orders stub</div> }));
vi.mock("@/components/options/FillsTable", () => ({ FillsTable: () => <div>fills stub</div> }));
vi.mock("@/components/options/ShortsTable", () => ({ ShortsTable: () => <div>shorts stub</div> }));

const submitCommand = vi.fn();
vi.mock("@/lib/commands", async () => {
  const actual = await vi.importActual("@/lib/commands");
  return {
    ...(actual as object),
    submitCommand: (...args: unknown[]) => submitCommand(...args),
  };
});

function nvda() {
  return {
    as_of: "x", id: 1, candidate_id: "c1", status: "pending",
    underlying: "NVDA", strategy: "cash_secured_put", right: "P",
    strike: 190.0, expiry: "2026-10-16", contracts: 1, premium: 3.25,
    blended_score: 72.0, created_at: "2026-09-01T00:00:00Z",
    expires_at: null, decided_at: null, order_state: null, source: "scan",
  };
}

function aapl() {
  return {
    as_of: "x", id: 2, candidate_id: "c2", status: "pending",
    underlying: "AAPL", strategy: "covered_call", right: "C",
    strike: 230.0, expiry: "2026-10-16", contracts: 1, premium: 2.1,
    blended_score: 65.0, created_at: "2026-09-01T00:00:00Z",
    expires_at: null, decided_at: null, order_state: null, source: "scan",
  };
}

function tslaRejected() {
  return {
    as_of: "x", id: 3, candidate_id: "c3", status: "rejected",
    underlying: "TSLA", strategy: "cash_secured_put", right: "P",
    strike: 260.0, expiry: "2026-10-16", contracts: 1, premium: 4.1,
    blended_score: 70.0, created_at: "2026-08-30T00:00:00Z",
    expires_at: null, decided_at: "2026-08-30T01:00:00Z", order_state: null, source: "scan",
  };
}

function msftExpired() {
  return {
    as_of: "x", id: 4, candidate_id: "c4", status: "expired",
    underlying: "MSFT", strategy: "covered_call", right: "C",
    strike: 420.0, expiry: "2026-10-16", contracts: 1, premium: 5.0,
    blended_score: 68.0, created_at: "2026-08-29T00:00:00Z",
    expires_at: null, decided_at: null, order_state: null, source: "scan",
  };
}

function amznApproved() {
  return {
    as_of: "x", id: 5, candidate_id: "c5", status: "approved",
    underlying: "AMZN", strategy: "cash_secured_put", right: "P",
    strike: 180.0, expiry: "2026-10-16", contracts: 1, premium: 3.5,
    blended_score: 75.0, created_at: "2026-08-31T00:00:00Z",
    expires_at: null, decided_at: "2026-08-31T01:00:00Z", order_state: "filled", source: "scan",
  };
}

// Whatever `submitCommand` last resolved to is also what a poll of
// `GET /commands/{id}` reports — otherwise <DecideControls/>'s own status
// poll (real, unmocked react-query) would overwrite it with the catch-all
// stub below and corrupt `current`.
let lastCommand: Record<string, unknown> | null = null;

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(async (path: string) => {
    if (path.startsWith("/options/approvals?status=all")) {
      return {
        as_of: "x",
        approvals: [nvda(), aapl(), tslaRejected(), msftExpired(), amznApproved()],
      };
    }
    if (path.startsWith("/options/approvals")) {
      return { as_of: "x", approvals: [nvda(), aapl()] };
    }
    if (path.startsWith("/options/controls")) {
      return {
        as_of: "x", autonomy: { level: "manual", label: "Manual" }, rungs: [],
        halted: false, halt_reason: null, mode: "paper",
        drain_healthy: true, drain_last_seen: null, pending_commands: 0,
      };
    }
    if (/^\/commands\/\d+$/.test(path) && lastCommand) {
      return lastCommand;
    }
    return {};
  }),
}));

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function dialogConfirm() {
  const dialog = screen.getByRole("dialog");
  const buttons = dialog.querySelectorAll<HTMLButtonElement>("button");
  return buttons[buttons.length - 1];
}

describe("OptionsPage — Decided tab", () => {
  it("has a Decided tab", () => {
    withClient(<OptionsPage />);
    expect(screen.getByRole("button", { name: "Decided" })).toBeDefined();
  });

  it("shows approved, rejected, and expired approvals, not pending ones", async () => {
    withClient(<OptionsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Decided" }));
    expect(await screen.findByText(/TSLA/)).toBeDefined();
    expect(screen.getByText(/MSFT/)).toBeDefined();
    // An approved approval — the outcome the flow most needs to keep visible —
    // must not silently drop off both the Approvals and Submitted views.
    expect(screen.getByText(/AMZN/)).toBeDefined();
    expect(screen.queryByText(/NVDA/)).toBeNull();
    expect(screen.queryByText(/AAPL/)).toBeNull();
  });

  it("renders each row's decision, not action controls", async () => {
    withClient(<OptionsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Decided" }));
    await screen.findByText(/TSLA/);
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });
});

describe("OptionsPage — ticker pill bar (filters the Approvals list)", () => {
  it("renders one pill per ticker present in the Approvals list", async () => {
    withClient(<OptionsPage />);
    expect(await screen.findByRole("button", { name: /NVDA/ })).toBeDefined();
    expect(screen.getByRole("button", { name: /AAPL/ })).toBeDefined();
  });

  it("filters the Approvals list to that ticker when its pill is clicked", async () => {
    withClient(<OptionsPage />);
    await screen.findByText(/NVDA 190/); // the card, not the pill
    screen.getByText(/AAPL 230/); // both cards present before filtering

    fireEvent.click(screen.getByRole("button", { name: /^AAPL/ }));

    expect(screen.getByText(/AAPL 230/)).toBeDefined();
    expect(screen.queryByText(/NVDA 190/)).toBeNull();
    // The pill itself survives the filter — it's how you'd pick a different
    // ticker, or clear this one, without losing the option to switch back.
    expect(screen.getByRole("button", { name: /^NVDA/ })).toBeDefined();
  });

  it("clears the filter when the same pill is clicked again", async () => {
    withClient(<OptionsPage />);
    await screen.findByText(/NVDA 190/);
    const aaplPill = screen.getByRole("button", { name: /^AAPL/ });
    fireEvent.click(aaplPill);
    expect(screen.queryByText(/NVDA 190/)).toBeNull();

    fireEvent.click(aaplPill);
    expect(await screen.findByText(/NVDA 190/)).toBeDefined();
  });

  it("does not render on the Submitted tab", async () => {
    withClient(<OptionsPage />);
    await screen.findByText(/NVDA 190/);
    fireEvent.click(screen.getByRole("button", { name: "Submitted" }));
    await screen.findByText(/No approvals submitted yet/i);
    expect(screen.queryByTestId("ticker-pill-bar")).toBeNull();
  });
});

describe("OptionsPage — Submitted tab (M3b)", () => {
  it("has a Submitted tab next to Approvals", () => {
    withClient(<OptionsPage />);
    expect(screen.getByRole("button", { name: "Submitted" })).toBeDefined();
  });

  it("moves a card to the Submitted tab the moment Approve is confirmed", async () => {
    lastCommand = {
      id: 41, kind: "approve", status: "pending", result: null,
      needs_confirmation: false, confirm_token: null,
      created_at: "x", applied_at: null, as_of: "x", created: true,
    };
    submitCommand.mockResolvedValueOnce(lastCommand);
    withClient(<OptionsPage />);
    await screen.findByText(/NVDA 190/);
    // NVDA's card is first; AAPL's Approve button must be left alone.
    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);
    fireEvent.click(dialogConfirm());

    // Gone from Approvals — moved the instant Approve was confirmed, not
    // waiting for the drain to actually apply it. AAPL is untouched.
    await waitFor(() => expect(screen.queryByText(/NVDA/)).toBeNull());
    expect(screen.getByText(/AAPL 230/)).toBeDefined();

    // Present in Submitted, with its in-flight receipt intact (M3b:
    // initialCommand carries it across the remount) — no pill bar on this
    // tab, so the bare symbol text is unambiguous here.
    fireEvent.click(screen.getByRole("button", { name: "Submitted" }));
    expect(await screen.findByText(/NVDA/)).toBeDefined();
    expect(screen.getByTestId("command-receipt")).toBeDefined();

    // And AAPL is the only thing left in Approvals.
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    await screen.findByText(/AAPL 230/);
    expect(screen.queryByText(/NVDA/)).toBeNull();
  });

  it("returns a card to Approvals if the submitted command fails", async () => {
    lastCommand = {
      id: 41, kind: "approve", status: "failed", result: { reason: "gate_rejected" },
      needs_confirmation: false, confirm_token: null,
      created_at: "x", applied_at: null, as_of: "x", created: true,
    };
    submitCommand.mockResolvedValueOnce(lastCommand);
    withClient(<OptionsPage />);
    await screen.findByText(/NVDA 190/);
    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);
    fireEvent.click(dialogConfirm());
    await waitFor(() => expect(screen.queryByText(/NVDA/)).toBeNull());

    // A failed command settles straight back out of "Submitted" — the
    // approval never actually left "pending" server-side.
    fireEvent.click(screen.getByRole("button", { name: "Submitted" }));
    expect(await screen.findByText(/No approvals submitted yet/i)).toBeDefined();

    // And it's back in Approvals, ready to retry — both the card and its
    // pill reappear now that it's no longer excluded as "submitted".
    fireEvent.click(screen.getByRole("button", { name: "Approvals" }));
    expect(await screen.findByText(/NVDA 190/)).toBeDefined();
  });
});

describe("OptionsPage — reload persistence (localStorage)", () => {
  it("restores a card's Submitted placement and receipt on a fresh mount", async () => {
    const { savePersistedCommand } = await import("@/lib/commands");
    const command = {
      id: 41, kind: "approve", status: "pending" as const, result: null,
      needs_confirmation: false, confirm_token: null,
      created_at: "x", applied_at: null, as_of: "x",
    };
    lastCommand = command;
    savePersistedCommand(1, command);

    withClient(<OptionsPage />);
    // NVDA never appears in Approvals — excluded from the very first render
    // this time, not moved there interactively.
    await screen.findByText(/AAPL 230/);
    expect(screen.queryByText(/NVDA/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Submitted" }));
    expect(await screen.findByText(/NVDA/)).toBeDefined();
    expect(screen.getByTestId("command-receipt")).toBeDefined();
  });
});
