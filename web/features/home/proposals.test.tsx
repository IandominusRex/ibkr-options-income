import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { NeedsYou } from "./NeedsYou";
import { ProposalsBanner } from "./ProposalsBanner";

const review = {
  why_attractive: "IV rank 62, premium 18% above fair value.",
  risks: "Earnings Oct 30 sits inside the window.",
  tradeoffs: "",
  assignment_considerations: "",
  rolling_considerations: "Roll down and out, or take the shares at $177.65 net.",
  summary: "",
};

function approval(id: number, over: Record<string, unknown> = {}) {
  return {
    as_of: "",
    id,
    candidate_id: `c${id}`,
    status: "pending",
    underlying: "AAPL",
    strategy: "cash_secured_put",
    right: "P",
    strike: 180,
    expiry: "2099-11-21",
    contracts: 1,
    premium: 2.35,
    blended_score: 0.7,
    created_at: "2026-10-13T13:00:00Z",
    expires_at: null,
    decided_at: null,
    order_state: null,
    source: "scan",
    review,
    rationale_tags: [],
    ...over,
  };
}

const controls = {
  as_of: "",
  autonomy: { level: "approve", label: "Approve each trade" },
  rungs: [],
  halted: false,
  halt_reason: null,
  halted_at: null,
  mode: "paper",
  drain_healthy: true,
  drain_last_seen: null,
  pending_commands: 0,
};

const list = (...a: unknown[]) => ({ as_of: "", approvals: a });

describe("NeedsYou", () => {
  it("shows Claude's review collapsed, above the stub", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(approval(1)),
      "/options/controls": controls,
    });
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    const why = within(card).getByRole("button", { name: /Why this trade/ });
    expect(why).toHaveAttribute("aria-expanded", "false");
    const stub = within(card).getByRole("group", { name: "AAPL put math" });
    expect(why.compareDocumentPosition(stub) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(why);
    expect(within(card).getByText("IV rank 62, premium 18% above fair value.")).toBeVisible();
    expect(within(card).getByText(/Claude's review/)).toBeInTheDocument();
  });
  it("leaves out the Why section when there is no review", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(approval(1, { review: null })),
      "/options/controls": controls,
    });
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(card).queryByRole("button", { name: /Why this trade/ })).toBeNull();
  });
  it("filters by strategy", async () => {
    renderWithQuery(<NeedsYou strategy="cc" />, {
      "/options/approvals": list(approval(1), approval(2, { strategy: "covered_call", right: "C", underlying: "KO", strike: 72 })),
      "/options/controls": controls,
    });
    expect(await screen.findByRole("article", { name: "KO · Sell $72 call" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "AAPL · Sell $180 put" })).toBeNull();
  });
  it("says spreads need nothing from you", async () => {
    renderWithQuery(<NeedsYou strategy="spread" />, {
      "/options/approvals": list(approval(1)),
      "/options/controls": controls,
    });
    expect(await screen.findByText("Credit spreads trade on their own in paper. Nothing here needs you.")).toBeInTheDocument();
  });
  // Review fix (whole-branch, Important): an unknown value book is not an empty one. Under All, with no wheel
  // proposal, "Nothing needs you right now." beside "a value proposal may be waiting" contradicted itself.
  const valueBook = (over: Record<string, unknown> = {}) => ({
    as_of: "2026-11-05T15:00:00Z", available: true, enabled: true, ceiling_usd: 30000, used_usd: 0, positions: [],
    proposals: [], funding: [], release_max_closes: 2, drain_healthy: true, drain_last_seen: null, ...over,
  });
  const couldNotRead = "The value book could not be read, so a value proposal may be waiting.";
  it("says so when nothing is waiting and the value book was read empty", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(),
      "/options/controls": controls,
      "/value/book": valueBook(),
    });
    expect(await screen.findByText("Nothing needs you right now.")).toBeInTheDocument();
  });
  it("says so when the value book is off and never wrote (nothing to miss)", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(),
      "/options/controls": controls,
      "/value/book": valueBook({ available: false, enabled: false }),
    });
    expect(await screen.findByText("Nothing needs you right now.")).toBeInTheDocument();
    expect(screen.queryByText(couldNotRead)).toBeNull();
  });
  it("says so under a filter that does not show the value book, whatever the book does", async () => {
    renderWithQuery(<NeedsYou strategy="cc" />, { "/options/approvals": list(), "/options/controls": controls });
    expect(await screen.findByText("Nothing needs you right now.")).toBeInTheDocument();
  });
  it("does not say nothing needs you when the value book request failed", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, { "/options/approvals": list(), "/options/controls": controls });
    expect(await screen.findByText(couldNotRead)).toBeInTheDocument();
    expect(screen.queryByText("Nothing needs you right now.")).toBeNull();
  });
  it("does not say nothing needs you when the value book is on but unreadable", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(),
      "/options/controls": controls,
      "/value/book": valueBook({ available: false, enabled: true }),
    });
    expect(await screen.findByText(couldNotRead)).toBeInTheDocument();
    expect(screen.queryByText("Nothing needs you right now.")).toBeNull();
  });
  it("Review opens the sheet with the decide controls; the card itself decides nothing", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(approval(1)),
      "/options/controls": controls,
    });
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(card).queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(within(card).queryByRole("button", { name: /Reject/ })).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Review" }));
    const sheet = screen.getByRole("dialog", { name: "Review trade" });
    expect(within(sheet).getByRole("button", { name: /Approve/ })).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Details" })).toHaveAttribute("href", "/trades/1");
  });
  it("Review tells assistive tech that it opens a dialog", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(approval(1)),
      "/options/controls": controls,
    });
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(card).getByRole("button", { name: "Review" })).toHaveAttribute("aria-haspopup", "dialog");
  });
  it("never invents a premium: an unknown one reads n/a, in the sentence and in every derived line", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(approval(1, { premium: null })),
      "/options/controls": controls,
    });
    const card = await screen.findByRole("article", { name: "AAPL · Sell $180 put" });
    expect(within(card).getByText(/Premium not known yet\./)).toBeInTheDocument();
    const stub = within(card).getByRole("group", { name: "AAPL put math" });
    expect(within(stub).getAllByText("n/a")).toHaveLength(3);
    expect(within(stub).queryByText("$0")).toBeNull();
    expect(within(stub).queryByText("0.00%")).toBeNull();
  });
  it("names the strategy in words and gives a roll its own card", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(approval(1), approval(2, { source: "roll", underlying: "AMD", strike: 150 })),
      "/options/controls": controls,
    });
    expect(await screen.findByText("Cash-secured put")).toBeInTheDocument();
    const roll = screen.getByRole("article", { name: "AMD · Roll" });
    expect(within(roll).getByText("Roll")).toBeInTheDocument();
    expect(within(roll).getByText(/This rolls a position you already hold/)).toBeInTheDocument();
    expect(within(roll).queryByRole("group")).toBeNull();
  });
  it("names a roll's two legs and sums them to the net", async () => {
    const leg = { strike: 250, expiry: "2099-10-23", right: "P", contracts: 1, old_mid: 2.1, new_mid: 3.275 };
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(
        approval(9, { source: "roll", strategy: "roll", strike: 250, expiry: "2099-10-28", premium: 1.175, roll_from: leg }),
      ),
      "/options/controls": controls,
    });
    const card = await screen.findByRole("article", { name: "AAPL · Roll $250 put Oct 23 → Oct 28" });
    const stub = within(card).getByRole("group", { name: "AAPL roll math" });
    expect(within(stub).getByText("Net credit")).toBeInTheDocument();
    expect(within(card).getByText(/At the quotes it was priced at/)).toBeInTheDocument();
  });

  it("says a roll without recorded legs has none, never inventing them", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(approval(9, { source: "roll", strategy: "roll", roll_from: null })),
      "/options/controls": controls,
    });
    const card = await screen.findByRole("article", { name: "AAPL · Roll" });
    expect(within(card).getByText(/legs were not recorded/)).toBeInTheDocument();
    expect(within(card).queryByRole("group", { name: /math/ })).toBeNull();
  });
  it("counts the waiting proposals in its heading", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, {
      "/options/approvals": list(approval(1), approval(2, { underlying: "KO" })),
      "/options/controls": controls,
    });
    expect(await screen.findByRole("heading", { name: "Needs you · 2 proposals" })).toBeInTheDocument();
  });
  it("says so in a sentence when proposals cannot load", async () => {
    renderWithQuery(<NeedsYou strategy="all" />, { "/options/controls": controls });
    expect(await screen.findByText("Proposals unavailable right now.")).toBeInTheDocument();
  });
});

describe("ProposalsBanner", () => {
  it("counts and names what is waiting and links to Trades", async () => {
    renderWithQuery(<ProposalsBanner strategy="all" />, {
      "/options/approvals": list(approval(1), approval(2, { strategy: "covered_call", right: "C", underlying: "KO", strike: 72 })),
    });
    expect(await screen.findByText("2 proposals need you")).toBeInTheDocument();
    expect(screen.getByText("AAPL put · KO call")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open/ })).toHaveAttribute("href", "/trades");
  });
  it("names where Open goes, for a screen reader that hears the link out of context", async () => {
    renderWithQuery(<ProposalsBanner strategy="all" />, { "/options/approvals": list(approval(1)) });
    expect(await screen.findByRole("link", { name: "Open Trades" })).toHaveAttribute("href", "/trades");
  });
  it("uses the singular for one proposal", async () => {
    renderWithQuery(<ProposalsBanner strategy="all" />, { "/options/approvals": list(approval(1)) });
    expect(await screen.findByText("1 proposal needs you")).toBeInTheDocument();
  });
  it("renders nothing when nothing is waiting", async () => {
    const { container } = renderWithQuery(<ProposalsBanner strategy="all" />, { "/options/approvals": list() });
    await new Promise((r) => setTimeout(r, 0));
    expect(container.textContent).toBe("");
  });
  it("renders nothing under Credit spreads, which need nobody", async () => {
    const { container } = renderWithQuery(<ProposalsBanner strategy="spread" />, { "/options/approvals": list(approval(1)) });
    await new Promise((r) => setTimeout(r, 0));
    expect(container.textContent).toBe("");
  });
});
