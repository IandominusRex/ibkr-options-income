import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";
// test-query first: it registers the "@/lib/api" mock, which must be in place before anything that
// imports apiFetch (lib/commands, RollCard) resolves.
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ApiError } from "@/lib/api";
import { savePersistedCommand } from "@/lib/commands";
import { RollCard } from "./RollCard";

const SYMBOL = "AAPL  261121P00180000";

const controls = {
  as_of: "", autonomy: { level: "approve", label: "Approve each trade" }, rungs: [], halted: false,
  halt_reason: null, halted_at: null, mode: "paper", drain_healthy: true, drain_last_seen: null,
  pending_commands: 0,
};

const shorts = (alerts: unknown[]) => ({
  as_of: "",
  shorts: [
    {
      as_of: "", position_symbol: SYMBOL, underlying: "AAPL", right: "P", strike: 180, expiry: "2026-11-21",
      dte: 33, contracts: 1, avg_cost: 2.35, mark: 0.6, unrealized_pnl: 175, pnl_pct: 74, delta: null,
      assignment_risk: false, alerts,
    },
  ],
});

const alert = {
  id: 1, trigger: "delta_breach", trigger_label: "Delta breach", detail: "Delta reached -0.42.",
  claude_recommendation: "Roll down and out.", created_at: new Date(Date.now() - 3 * 3_600_000 - 60_000).toISOString(),
};

const command = (over: Record<string, unknown> = {}) => ({
  id: 51, kind: "roll_request", status: "pending", result: null, needs_confirmation: false,
  confirm_token: null, created_at: "x", applied_at: null, as_of: "x", created: true, ...over,
});

function writes(): Array<[unknown, unknown]> {
  return apiFetchMock.mock.calls
    .filter((c) => (c[1] as RequestInit | undefined)?.method === "POST")
    .map((c) => [c[0], JSON.parse(String((c[1] as RequestInit).body))]);
}

const card = <RollCard underlying="AAPL" symbol={SYMBOL} strike={180} right="P" />;

function confirmDialog() {
  const dialog = screen.getByRole("dialog");
  const buttons = dialog.querySelectorAll("button");
  fireEvent.click(buttons[buttons.length - 1]);
}

beforeEach(() => {
  (apiFetchMock as unknown as { mockClear: () => void }).mockClear();
  localStorage.clear();
});

describe("RollCard", () => {
  it("lists the alerts fired on this contract, with Claude's view labelled", async () => {
    renderWithQuery(card, { "/options/shorts": shorts([alert]), "/options/controls": controls });
    expect(await screen.findByText("Delta breach")).toBeInTheDocument();
    expect(screen.getByText("Delta reached -0.42.")).toBeInTheDocument();
    expect(screen.getByText("3h ago")).toBeInTheDocument();
    expect(screen.getByText("Claude's view:")).toBeInTheDocument();
    expect(screen.getByText(/Roll down and out\./)).toBeInTheDocument();
  });

  it("says so when no alert has fired", async () => {
    renderWithQuery(card, { "/options/shorts": shorts([]), "/options/controls": controls });
    expect(await screen.findByText("No roll alert has fired on this contract.")).toBeInTheDocument();
  });

  it("is a secondary button, never lime: it proposes, it does not trade", async () => {
    renderWithQuery(card, { "/options/shorts": shorts([]), "/options/controls": controls });
    expect(await screen.findByRole("button", { name: "Propose a roll" })).toHaveAttribute("data-variant", "secondary");
  });

  it("opens the confirmation before any request", async () => {
    renderWithQuery(card, { "/options/shorts": shorts([]), "/options/controls": controls });
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(writes()).toEqual([]);
  });

  it("sends one roll_request with the contract's symbol on confirm, then shows the receipt", async () => {
    renderWithQuery(card, { "/options/shorts": shorts([]), "/options/controls": controls, "/commands": command() });
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    confirmDialog();
    await waitFor(() => expect(writes()).toEqual([["/commands", { kind: "roll_request", payload: { position_symbol: SYMBOL } }]]));
    expect(await screen.findByTestId("command-receipt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Propose a roll" })).toBeDisabled();
  });

  it("answers no_qualifying_roll in plain words, not as an error", async () => {
    renderWithQuery(card, {
      "/options/shorts": shorts([]),
      "/options/controls": controls,
      "/commands": command({ status: "failed", result: { reason: "no_qualifying_roll", detail: {} } }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Propose a roll" }));
    confirmDialog();
    const receipt = await screen.findByTestId("command-receipt");
    expect(receipt.getAttribute("data-state")).toBe("answered");
    expect(within(receipt).getByText(/real answer, not an error/)).toBeInTheDocument();
  });

  it("says the alerts could not be read, and still offers the roll", async () => {
    renderWithQuery(card, { "/options/controls": controls });
    expect(await screen.findByText("Roll alerts could not be loaded right now.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Propose a roll" })).toBeEnabled();
  });
});

/**
 * The roll flow's own cases, ported from the deleted Shorts table's suite (web overhaul Part 4,
 * Task 6): RollCard is the live mount of useRollProposal, so these pin the confirm step, the
 * receipt links, the in-flight lock, the 403 words, the live second confirmation and the reload
 * persistence. They answer the /commands POSTs through apiFetchMock, as the cases above do.
 */
function mountRoll(
  {
    post = async () => command(),
    polled = command(),
  }: { post?: () => Promise<unknown>; polled?: unknown } = {},
) {
  apiFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      if (path === "/commands") return post();
      if (path.endsWith("/confirm")) return undefined;
      throw new Error(`unexpected POST ${path}`);
    }
    if (path.startsWith("/options/shorts")) return shorts([]);
    if (path.startsWith("/options/controls")) return controls;
    if (path.startsWith("/commands/")) return polled;
    throw new Error(`unexpected fetch ${path}`);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{card}</QueryClientProvider>);
}

const proposeButton = () => screen.findByRole("button", { name: "Propose a roll" });
const proposeAndConfirm = async () => {
  fireEvent.click(await proposeButton());
  confirmDialog();
};

describe("RollCard - the roll flow (ported from the Shorts table)", () => {
  it("renders one Propose a roll control", async () => {
    mountRoll();
    expect(await screen.findAllByRole("button", { name: "Propose a roll" })).toHaveLength(1);
  });

  it("the control's label says what it does (Propose a roll, not Roll)", async () => {
    mountRoll();
    expect(await proposeButton()).toBeInTheDocument();
    // No bare "Roll" button: the copy must not imply the button rolls the position.
    expect(screen.queryByRole("button", { name: "Roll" })).toBeNull();
  });

  it("the dialog states plainly: price a roll, raise for approval, nothing executes until approved", async () => {
    mountRoll();
    fireEvent.click(await proposeButton());
    const summary = screen.getByTestId("confirm-summary").textContent ?? "";
    expect(summary).toMatch(/price a roll/i);
    expect(summary).toMatch(/approval/i);
    expect(summary).toMatch(/nothing executes until/i);
    // House style: no em dashes, no banned words.
    expect(summary).not.toContain("\u2014");
    for (const banned of ["seamless", "robust", "unlock", "elevate"]) {
      expect(summary.toLowerCase()).not.toContain(banned);
    }
  });

  it("roll_already_working links to the existing approval", async () => {
    mountRoll({
      post: async () =>
        command({ status: "failed", result: { reason: "roll_already_working", detail: { approval_id: 77 } } }),
    });
    await proposeAndConfirm();
    const link = (await screen.findByRole("link", { name: /roll already in flight/i })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/trades/77");
  });

  it("on success the receipt links to the new approval", async () => {
    mountRoll({
      post: async () => command({ status: "applied", result: { approval_id: 99, candidate_id: "abc" } }),
    });
    await proposeAndConfirm();
    const link = (await screen.findByRole("link", { name: /view approval/i })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/trades/99");
  });

  it("the control is disabled while a roll command for that position is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    mountRoll({ post: () => new Promise((r) => (resolve = r)) });
    const button = await proposeButton();
    fireEvent.click(button);
    confirmDialog();
    await waitFor(() => expect(button).toBeDisabled());
    resolve(command());
  });

  it("renders a permission message on a 403, not a generic failure", async () => {
    mountRoll({
      post: async () => {
        throw new ApiError(403, "forbidden");
      },
    });
    await proposeAndConfirm();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert").textContent).toContain("permission");
    expect(screen.getByRole("alert").textContent).not.toContain("could not be created");
  });

  describe("live-mode second confirmation", () => {
    const live = () => command({ needs_confirmation: true, confirm_token: "tok-abc" });

    it("renders the live step as a distinct, clearly labelled step, not a repeat", async () => {
      mountRoll({ post: async () => live() });
      fireEvent.click(await proposeButton());
      const firstCopy = screen.getByRole("dialog").textContent ?? "";
      confirmDialog();

      const liveDialog = await screen.findByRole("dialog");
      expect(liveDialog.textContent).toContain("LIVE");
      expect(liveDialog.textContent).not.toBe(firstCopy);

      confirmDialog();
      await waitFor(() =>
        expect(writes()).toContainEqual(["/commands/51/confirm", { confirm_token: "tok-abc" }]),
      );
    });

    it("disables Propose a roll while the live confirmation dialog is open, before it is released", async () => {
      // Regression: `inFlight` used to ignore `liveStep`, so the control stayed clickable during
      // the window between the first confirm and the live release (no command id to poll yet).
      mountRoll({ post: async () => live() });
      await proposeAndConfirm();
      await screen.findAllByText(/LIVE/);
      expect(screen.getByRole("button", { name: "Propose a roll" })).toBeDisabled();
    });

    it("keeps the command pending (needs_confirmation) if the live step is cancelled", async () => {
      mountRoll({ post: async () => live() });
      await proposeAndConfirm();
      await screen.findAllByText(/LIVE/);
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      expect(writes().some(([path]) => String(path).endsWith("/confirm"))).toBe(false);
      const receipt = await screen.findByTestId("command-receipt");
      expect(receipt.getAttribute("data-state")).toBe("queued");
    });
  });

  describe("reload persistence (localStorage)", () => {
    it("restores an in-flight receipt from localStorage on a fresh mount", async () => {
      savePersistedCommand(`short:${SYMBOL}`, command({ created: undefined }) as never);
      mountRoll();
      expect(await screen.findByTestId("command-receipt")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Propose a roll" })).toBeDisabled();
    });

    it("restores the live second-confirmation dialog from localStorage on a fresh mount", async () => {
      savePersistedCommand(
        `short:${SYMBOL}`,
        command({ needs_confirmation: true, confirm_token: "tok-abc", created: undefined }) as never,
      );
      mountRoll();
      const dialog = await screen.findByRole("dialog");
      expect(dialog.textContent).toContain("LIVE");
    });
  });
});
