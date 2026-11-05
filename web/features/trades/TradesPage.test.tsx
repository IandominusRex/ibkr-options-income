import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
// test-query registers the @/lib/api mock when it is evaluated, so it must load before anything
// that imports @/lib/api (lib/commands does), or that module keeps the real apiFetch.
import { apiFetchMock } from "@/lib/test-query";
import { loadPersistedCommand, savePersistedCommand, type CommandStatus } from "@/lib/commands";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/trades",
}));

import { TradesPage } from "./TradesPage";

const aapl = {
  as_of: "", id: 1, candidate_id: "c1", status: "pending", underlying: "AAPL",
  strategy: "cash_secured_put", right: "P", strike: 180, expiry: "2099-11-21", contracts: 1,
  premium: 2.35, blended_score: 0.7, created_at: "2026-10-13T13:00:00Z", expires_at: null,
  decided_at: null, order_state: null, source: "scan", review: null, rationale_tags: [],
};

const pendingCommand = {
  id: 7, kind: "approve", status: "pending", result: null, needs_confirmation: false,
  confirm_token: null, created_at: "", applied_at: null, as_of: "",
};

type World = {
  drainHealthy?: boolean;
  pending?: unknown[];
  /** The pending-approvals request rejects (the API is down, or answers 500). */
  pendingFails?: boolean;
  /** What a poll of GET /commands/{id} answers; the Approve itself (POST /commands) is always pending. */
  command?: { status: "pending" | "failed" | "expired"; needs_confirmation?: boolean };
};

function serve(world: World = {}) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === "/options/approvals?status=pending") {
      if (world.pendingFails) throw new Error("API unavailable");
      return { as_of: "", approvals: world.pending ?? [aapl] };
    }
    if (path.startsWith("/options/approvals?status=all")) return { as_of: "", approvals: [] };
    if (path === "/options/approvals/1") return aapl;
    if (path === "/options/controls") {
      return {
        as_of: "", autonomy: { level: "full", label: "Full" }, rungs: [], halted: false,
        halt_reason: null, halted_at: null, mode: "paper", drain_healthy: world.drainHealthy ?? true,
        drain_last_seen: null, pending_commands: 0,
      };
    }
    if (path.startsWith("/options/orders")) return { as_of: "", orders: [] };
    if (path.startsWith("/options/assessed")) return { as_of: "", run_id: "r1", computed_at: null, groups: [] };
    if (path.startsWith("/pnl/day")) {
      return {
        as_of: "", date: "2026-10-15", book: "paper", strategy: "all", trades: [], spreads_available: true,
        previous_day: null, next_day: null,
      };
    }
    if (path.startsWith("/spreads/picks")) {
      return {
        as_of: "", available: true, underlying: "SPY", mode: "paper", ai_enabled: true, day: "2026-10-15",
        previous_day: null, next_day: null, picks: [], positions: [],
      };
    }
    if (path === "/commands") return { ...pendingCommand, created: true };
    if (path.startsWith("/commands/")) return { ...pendingCommand, ...world.command };
    throw new Error(`no mocked response for ${path}`);
  });
}

const tree = (qc: QueryClient) => (
  <QueryClientProvider client={qc}>
    <TradesPage />
  </QueryClientProvider>
);

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const r = render(tree(qc));
  return { qc, rerenderPage: () => r.rerender(tree(qc)) };
}

const viewNames = (group: HTMLElement) =>
  within(group)
    .getAllByRole("button")
    .map((b) => (b.textContent ?? "").replace(/\s*\d+$/, "").trim());

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
  localStorage.clear();
  (apiFetchMock as unknown as { mockClear: () => void }).mockClear();
  serve();
});

describe("TradesPage", () => {
  it("names the page, then the strategy switcher, then three views; a waiting proposal opens Proposals", async () => {
    mount();
    expect(await screen.findByRole("heading", { level: 1, name: "Trades" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Strategy" })).toBeInTheDocument();
    const views = await screen.findByRole("group", { name: "View" });
    expect(viewNames(views)).toEqual(["Proposals", "History", "Assessed"]);
    expect(await within(views).findByRole("button", { name: /^Proposals/ })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("article", { name: "AAPL · Sell $180 put" })).toBeInTheDocument();
  });

  it("opens History when nothing waits on you", async () => {
    serve({ pending: [] });
    mount();
    const views = await screen.findByRole("group", { name: "View" });
    await waitFor(() => expect(within(views).getByRole("button", { name: /^History/ })).toHaveAttribute("aria-pressed", "true"));
    expect(await screen.findByRole("region", { name: "Traded" })).toBeInTheDocument();
  });

  it("gives Credit spreads one view, Spreads, and no view chips", async () => {
    nav.params = new URLSearchParams("strategy=spread");
    mount();
    expect(await screen.findByText(/No spread was opened on this day/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "View" })).toBeNull();
  });

  it("opens the default for a junk ?view=, and History for a retired one", async () => {
    nav.params = new URLSearchParams("view=foo");
    const { rerenderPage } = mount();
    expect(await screen.findByRole("article", { name: "AAPL · Sell $180 put" })).toBeInTheDocument();
    nav.params = new URLSearchParams("view=decided");
    rerenderPage();
    expect(await screen.findByRole("region", { name: "Traded" })).toBeInTheDocument();
  });

  it("passes ?day= to History", async () => {
    nav.params = new URLSearchParams("view=history&day=2026-10-09");
    mount();
    expect(await screen.findByRole("heading", { name: /Fri, Oct 9/ })).toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => c[0] === "/pnl/day?date=2026-10-09&strategy=all")).toBe(true);
  });

  it("opens Assessed filtered to ?symbol= (the link Top opportunities uses)", async () => {
    nav.params = new URLSearchParams("view=assessed&strategy=csp&symbol=googl");
    mount();
    const input = await screen.findByLabelText("Symbol");
    expect(input).toHaveValue("GOOGL");
    expect(
      apiFetchMock.mock.calls.some((c) => String(c[0]).startsWith("/options/assessed") && String(c[0]).includes("symbol=GOOGL")),
    ).toBe(true);
  });

  it("writes the view into the URL", async () => {
    mount();
    const views = await screen.findByRole("group", { name: "View" });
    fireEvent.click(within(views).getByRole("button", { name: /^History/ }));
    expect(nav.replace).toHaveBeenCalledWith("/trades?view=history", { scroll: false });
  });

  it("approving in the sheet moves the card to History at once, and the page stays on Proposals", async () => {
    const { rerenderPage } = mount();
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    fireEvent.click(within(card).getByRole("button", { name: "Review" }));
    const sheet = screen.getByRole("dialog", { name: "Review trade" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Approve" }));
    const confirm = within(sheet).getByRole("dialog", { name: "Approve this contract" });
    const buttons = confirm.querySelectorAll("button");
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(screen.queryByRole("article", { name: "AAPL · Sell $180 put" })).toBeNull());
    fireEvent.click(within(sheet).getByRole("button", { name: "Close" }));
    const views = screen.getByRole("group", { name: "View" });
    expect(within(views).getByRole("button", { name: /^Proposals/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Nothing needs you right now.")).toBeInTheDocument();
    await waitFor(() => expect(within(views).getByRole("button", { name: /^History/ }).textContent).toMatch(/1$/));

    nav.params = new URLSearchParams("view=history");
    rerenderPage();
    const flight = await screen.findByRole("region", { name: "In flight" });
    const sent = await within(flight).findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(sent).getByTestId("command-receipt")).toBeInTheDocument();
  });

  it("a reload mid-command keeps the card in flight, and so opens History", async () => {
    savePersistedCommand(1, pendingCommand as CommandStatus);
    mount();
    const flight = await screen.findByRole("region", { name: "In flight" });
    const sent = await within(flight).findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(sent).getByTestId("command-receipt")).toBeInTheDocument();
  });

  it("opens History, with the view chips, when the pending proposals could not be loaded", async () => {
    serve({ pendingFails: true });
    mount();
    const views = await screen.findByRole("group", { name: "View" });
    await waitFor(() => expect(within(views).getByRole("button", { name: /^History/ })).toHaveAttribute("aria-pressed", "true"));
    expect(await screen.findByRole("region", { name: "Traded" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading trades" })).toBeNull();
    // Proposals is one tap away and says for itself that it could not load.
    fireEvent.click(within(views).getByRole("button", { name: /^Proposals/ }));
    expect(nav.replace).toHaveBeenCalledWith("/trades?view=proposals", { scroll: false });
  });

  it("keeps History when the pending proposals load after the first attempt failed", async () => {
    const world: World = { pendingFails: true };
    serve(world);
    const { qc } = mount();
    const views = await screen.findByRole("group", { name: "View" });
    await waitFor(() => expect(within(views).getByRole("button", { name: /^History/ })).toHaveAttribute("aria-pressed", "true"));
    world.pendingFails = false;
    await act(async () => {
      await qc.invalidateQueries({ queryKey: ["options", "approvals", "pending"] });
    });
    await waitFor(() => expect(within(views).getByRole("button", { name: /^Proposals/ }).textContent).toMatch(/1$/));
    expect(within(views).getByRole("button", { name: /^History/ })).toHaveAttribute("aria-pressed", "true");
  });

  describe("an Approve that ends failed or expired, with the sheet closed and History never opened", () => {
    /** Review, Approve, confirm, close the sheet: the card is out of Proposals and in flight. */
    async function approveAndCloseTheSheet() {
      const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
      fireEvent.click(within(card).getByRole("button", { name: "Review" }));
      const sheet = screen.getByRole("dialog", { name: "Review trade" });
      fireEvent.click(within(sheet).getByRole("button", { name: "Approve" }));
      const confirm = within(sheet).getByRole("dialog", { name: "Approve this contract" });
      const buttons = confirm.querySelectorAll("button");
      fireEvent.click(buttons[buttons.length - 1]);
      await waitFor(() => expect(screen.queryByRole("article", { name: "AAPL · Sell $180 put" })).toBeNull());
      fireEvent.click(within(sheet).getByRole("button", { name: "Close" }));
      await waitFor(() => expect(screen.queryByRole("dialog", { name: "Review trade" })).toBeNull());
    }

    /** Stands in for the 2-second poll: ask the command's status again now. */
    const pollNow = (qc: QueryClient) =>
      act(async () => {
        await qc.invalidateQueries({ queryKey: ["command"] });
      });

    it.each(["failed", "expired"] as const)("hands the card back to Proposals when the command %s", async (status) => {
      const world: World = {};
      serve(world);
      const { qc } = mount();
      await approveAndCloseTheSheet();
      const views = screen.getByRole("group", { name: "View" });
      expect(within(views).getByRole("button", { name: /^Proposals/ })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByText("Nothing needs you right now.")).toBeInTheDocument();
      expect(loadPersistedCommand(1)).not.toBeNull();

      world.command = { status };
      await pollNow(qc);

      expect(await screen.findByRole("article", { name: "AAPL · Sell $180 put" })).toBeInTheDocument();
      await waitFor(() => expect(within(views).getByRole("button", { name: /^Proposals/ }).textContent).toMatch(/1$/));
      expect(within(views).getByRole("button", { name: /^Proposals/ })).toHaveAttribute("aria-pressed", "true");
      // The persisted entry is gone, so a later visit does not hide the card again.
      expect(loadPersistedCommand(1)).toBeNull();
    });

    it("does not hand a command back while it still waits on the LIVE confirmation", async () => {
      const world: World = {};
      serve(world);
      const { qc } = mount();
      await approveAndCloseTheSheet();
      world.command = { status: "pending", needs_confirmation: true };
      await pollNow(qc);
      expect(screen.queryByRole("article", { name: "AAPL · Sell $180 put" })).toBeNull();
      expect(screen.getByText("Nothing needs you right now.")).toBeInTheDocument();
      expect(loadPersistedCommand(1)).not.toBeNull();
    });

    it("follows a command carried over from a reload, with Proposals open", async () => {
      const world: World = { command: { status: "failed" } };
      serve(world);
      savePersistedCommand(1, pendingCommand as CommandStatus);
      nav.params = new URLSearchParams("view=proposals");
      mount();
      expect(await screen.findByRole("article", { name: "AAPL · Sell $180 put" })).toBeInTheDocument();
      await waitFor(() => expect(loadPersistedCommand(1)).toBeNull());
    });
  });

  it("warns in words when the trading service is not draining commands", async () => {
    serve({ drainHealthy: false });
    mount();
    expect(await screen.findByTestId("drain-dead-warning")).toBeInTheDocument();
  });

  it("hydrates over the server HTML even when the rail has already filled the shared cache", async () => {
    const html = renderToString(tree(new QueryClient()));
    const container = document.createElement("div");
    container.innerHTML = html;
    document.body.appendChild(container);
    const warm = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    warm.setQueryData(["options", "approvals", "pending"], { as_of: "", approvals: [aapl] });
    const errors: unknown[] = [];
    await act(async () => {
      hydrateRoot(container, tree(warm), { onRecoverableError: (e) => errors.push(e) });
    });
    expect(errors).toEqual([]);
    container.remove();
  });
});
