import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommandStatus } from "@/lib/commands";
import { apiFetchMock } from "@/lib/test-query";
import { ProposalsView } from "./ProposalsView";

function approval(id: number, underlying: string, over: Record<string, unknown> = {}) {
  return {
    as_of: "", id, candidate_id: `c${id}`, status: "pending", underlying,
    strategy: "cash_secured_put", right: "P", strike: 180, expiry: "2099-11-21", contracts: 1,
    premium: 2.35, blended_score: 0.7, created_at: "2026-10-13T13:00:00Z", expires_at: null,
    decided_at: null, order_state: null, source: "scan", review: null, rationale_tags: [],
    ...over,
  };
}

const controls = {
  as_of: "", autonomy: { level: "approve", label: "Approve each trade" }, rungs: [], halted: false,
  halt_reason: null, halted_at: null, mode: "paper", drain_healthy: true, drain_last_seen: null,
  pending_commands: 0,
};

const command = {
  id: 7, kind: "approve", status: "pending", result: null, needs_confirmation: false,
  confirm_token: null, created_at: "", applied_at: null, as_of: "", created: true,
};

type Approval = ReturnType<typeof approval>;

function mount(approvals: Approval[] | Error, props: { strategy?: "all" | "csp" | "cc"; submitted?: Map<number, CommandStatus> } = {}) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path.startsWith("/options/approvals?")) {
      if (approvals instanceof Error) throw approvals;
      return { as_of: "", approvals };
    }
    if (path.startsWith("/options/approvals/")) {
      const id = Number(path.split("/").pop());
      return (approvals as Approval[]).find((a) => a.id === id);
    }
    if (path === "/options/controls") return controls;
    if (path === "/commands" || path.startsWith("/commands/")) return command;
    throw new Error(`no mocked response for ${path}`);
  });
  const onSubmitted = vi.fn();
  const onSettled = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ProposalsView
        strategy={props.strategy ?? "all"}
        submitted={props.submitted ?? new Map()}
        onSubmitted={onSubmitted}
        onSettled={onSettled}
      />
    </QueryClientProvider>,
  );
  return { onSubmitted, onSettled };
}

beforeEach(() => {
  (apiFetchMock as unknown as { mockClear: () => void }).mockClear();
  localStorage.clear();
});

describe("ProposalsView", () => {
  it("shows every pending proposal as Home's card, with Review", async () => {
    mount([approval(1, "AAPL"), approval(2, "NVDA", { strike: 190 })]);
    const aapl = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(aapl).getByRole("button", { name: "Review" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "NVDA · Sell $190 put" })).toBeInTheDocument();
  });

  it("leaves out a proposal whose Approve is already in flight", async () => {
    mount([approval(1, "AAPL"), approval(2, "NVDA", { strike: 190 })], {
      submitted: new Map([[1, command as unknown as CommandStatus]]),
    });
    await screen.findByRole("article", { name: "NVDA · Sell $190 put" });
    expect(screen.queryByRole("article", { name: "AAPL · Sell $180 put" })).toBeNull();
  });

  it("opens a proposal's page carrying the view and the strategy, so Back returns here", async () => {
    mount([approval(1, "AAPL")], { strategy: "csp" });
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(card).getByRole("link", { name: "Details" })).toHaveAttribute("href", "/trades/1?view=proposals&strategy=csp");
  });

  it("under All the strategy is left out", async () => {
    mount([approval(1, "AAPL")]);
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(card).getByRole("link", { name: "Details" })).toHaveAttribute("href", "/trades/1?view=proposals");
  });

  it("filters by ticker and clears back to all", async () => {
    mount([approval(1, "AAPL"), approval(2, "NVDA", { strike: 190 }), approval(3, "NVDA", { strike: 185 })]);
    const chips = await screen.findByRole("group", { name: "Ticker" });
    fireEvent.click(within(chips).getByRole("button", { name: /^NVDA/ }));
    expect(screen.queryByRole("article", { name: "AAPL · Sell $180 put" })).toBeNull();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    fireEvent.click(within(chips).getByRole("button", { name: "All tickers" }));
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });

  it("shows no ticker chips when every proposal is on one ticker", async () => {
    mount([approval(1, "AAPL"), approval(2, "AAPL", { strike: 175 })]);
    await screen.findAllByRole("article");
    expect(screen.queryByRole("group", { name: "Ticker" })).toBeNull();
  });

  it("scopes to the strategy", async () => {
    mount(
      [approval(1, "AAPL"), approval(2, "MSFT", { strategy: "covered_call", right: "C", strike: 420 })],
      { strategy: "cc" },
    );
    expect(await screen.findByRole("article", { name: "MSFT · Sell $420 call" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "AAPL · Sell $180 put" })).toBeNull();
  });

  it("says nothing needs you when the list is empty", async () => {
    mount([]);
    expect(await screen.findByText("Nothing needs you right now.")).toBeInTheDocument();
  });

  it("names the retry when the list cannot be loaded", async () => {
    mount(new Error("down"));
    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument();
  });

  it("hands the card on through onSubmitted the instant Approve is confirmed", async () => {
    const { onSubmitted } = mount([approval(1, "AAPL")]);
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    fireEvent.click(within(card).getByRole("button", { name: "Review" }));
    const sheet = screen.getByRole("dialog", { name: "Review trade" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Approve" }));
    const confirm = within(sheet).getByRole("dialog", { name: "Approve this contract" });
    const buttons = confirm.querySelectorAll("button");
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith(1, expect.objectContaining({ id: 7 })));
  });
});
