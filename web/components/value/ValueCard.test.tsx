import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { ValueCard } from "./ValueCard";
import type { ValueBook, ValueProposal } from "./types";

afterEach(cleanup);

function proposal(over: Partial<ValueProposal> = {}): ValueProposal {
  return {
    id: 5, kind: "buy", symbol: "AAPL", list_name: "deep_value", shares: 20, price: 182.4, cost_usd: 3648,
    reason: "tranche 1", cause: "python", needs_tap: true, status: "pending",
    created_at: "2026-11-05T14:00:00Z", expires_at: "2099-01-01T00:00:00Z", fingerprint: "abc123def0", ...over,
  };
}

function book(over: Partial<ValueBook> = {}): ValueBook {
  return {
    as_of: "2026-11-05T15:00:00Z", available: true, enabled: true, ceiling_usd: 30000, used_usd: 7200,
    positions: [
      {
        id: 1, symbol: "MSFT", list_name: "quality_growth", status: "open", shares: 20, avg_cost: 150, mark: 165,
        opened_at: "2026-10-01", next_exit: { kind: "sell_half", level: 180 }, realised_usd: null,
      },
    ],
    proposals: [proposal()],
    funding: [],
    breakers: { trend: false, drawdown: false, drawdown_pct: 4.2, trim_offered: false, trim_episode: null, trimmed: false },
    release_max_closes: 2,
    ...over,
  };
}

function show(b: ValueBook, strategy: "all" | "csp" = "all") {
  return renderWithQuery(<ValueCard strategy={strategy} />, { "/value/book": b });
}

describe("ValueCard", () => {
  it("shows the ceiling as a sum, each position with its next exit in words, and the proposals", async () => {
    show(book());
    expect(await screen.findByRole("heading", { name: "Value book" })).toBeInTheDocument();
    expect(screen.getByText(/\$7,200 of \$30,000/)).toBeInTheDocument();
    const stub = screen.getByRole("group", { name: "Value book ceiling" });
    expect(within(stub).getByText("Room left")).toBeInTheDocument();
    expect(within(stub).getByText("$22,800.00")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText(/sell half at \$180\.00/)).toBeInTheDocument();
    expect(screen.getByText("Buy 20 AAPL")).toBeInTheDocument();
  });
  it("says the book has not written anything, never none, when value.db is missing", async () => {
    show(book({ available: false, ceiling_usd: null, used_usd: null, positions: [], proposals: [] }));
    expect(await screen.findByText("The value book has not written anything yet.")).toBeInTheDocument();
    expect(screen.queryByText(/none/i)).toBeNull();
  });
  it("says the book is off in words", async () => {
    show(book({ enabled: false, positions: [], proposals: [] }));
    expect(await screen.findByText(/The value book is off/)).toBeInTheDocument();
  });
  it("reads a ceiling that is not known yet as a hatched n/a, not $0", async () => {
    show(book({ ceiling_usd: null, used_usd: null }));
    await screen.findByRole("heading", { name: "Value book" });
    const na = screen.getAllByText("n/a").find((el) => el.className.includes("hatch"));
    expect(na).toBeDefined();
    expect(screen.queryByText("$0")).toBeNull();
  });
  it("shows Review on a proposal that waits for a tap, in lime", async () => {
    show(book());
    const review = await screen.findByRole("button", { name: "Review" });
    expect(review).toHaveAttribute("data-variant", "primary");
  });
  it("shows an auto-approved proposal as approved by the system, with no Review", async () => {
    show(book({ proposals: [proposal({ needs_tap: false, status: "approved" })] }));
    expect(await screen.findByText("Approved by the system")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review" })).toBeNull();
  });
  it("opens the review sheet with the decide controls, and no button carries Claude's words", async () => {
    show(book({ proposals: [proposal({ cause: "claude", kind: "sell", price: null, reason: "claude_no" })] }));
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    const sheet = await screen.findByRole("dialog", { name: "Review value trade" });
    expect(within(sheet).getByText(/Only Claude's number makes this sale/)).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Approve" })).toBeInTheDocument();
    for (const b of screen.getAllByRole("button")) {
      expect(b.textContent ?? "").not.toMatch(/Claude/);
    }
  });
  it("shows a tripped breaker as a flag word with a sentence", async () => {
    show(book({ breakers: { trend: true, drawdown: true, drawdown_pct: 21.5, trim_offered: false, trim_episode: null, trimmed: false } }));
    const trend = await screen.findByText("Trend brake on");
    expect(trend.closest("[data-tone]")).toHaveAttribute("data-tone", "flag");
    expect(screen.getByText("Drawdown stop on")).toHaveAttribute("data-tone", "flag");
    expect(screen.getByText(/21\.5% below its high/)).toBeInTheDocument();
  });
  it("reads an unknown breaker as a hatched n/a, not as off", async () => {
    show(book({ breakers: { trend: null, drawdown: false, drawdown_pct: null, trim_offered: false, trim_episode: null, trimmed: false } }));
    expect(await screen.findByText("Trend brake n/a")).toHaveClass("hatch");
  });
  it("offers the trim in Telegram only, with no web button", async () => {
    show(book({ breakers: { trend: false, drawdown: true, drawdown_pct: 26, trim_offered: true, trim_episode: "ep12345678", trimmed: false } }));
    expect(await screen.findByText(/Trim to half is offered in Telegram/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /trim/i })).toBeNull();
  });
  it("labels a missing next exit in plain words and hatches only the n/a, so the label stays readable", async () => {
    show(book({ positions: [{ id: 2, symbol: "INTC", list_name: "deep_value", status: "open", shares: 100, avg_cost: 21.4, mark: 22, opened_at: "2026-10-10", next_exit: null, realised_usd: null }] }));
    const na = await screen.findByText("n/a");
    expect(na).toHaveClass("hatch");
    expect(na.parentElement).toHaveTextContent("Next exit: n/a");
    expect(na.parentElement).not.toHaveClass("hatch");
  });
  it("starts the review sheet's expiry on its own line, as a sentence", async () => {
    show(book());
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    const sheet = await screen.findByRole("dialog", { name: "Review value trade" });
    expect(within(sheet).getByText(/^Expires in \d+d\.$/)).toBeInTheDocument();
  });
  it("lists a name waiting for cash", async () => {
    show(
      book({
        funding: [{ id: 1, proposal_id: 5, symbol: "AAPL", needed_usd: 1200, created_at: null, expires_at: null }],
      }),
    );
    expect(await screen.findByText(/AAPL is waiting for \$1,200\.00 of cash/)).toBeInTheDocument();
  });
  it("shows the card under All and nothing under a wheel filter", async () => {
    const { container } = show(book(), "csp");
    expect(container).toBeEmptyDOMElement();
  });
  it("says it could not load, in words, when the request fails", async () => {
    renderWithQuery(<ValueCard strategy="all" />, {});
    expect(await screen.findByText(/The value book could not be loaded/)).toBeInTheDocument();
  });
  it("shows the card under the Value filter too, with the same book", async () => {
    renderWithQuery(<ValueCard strategy="value" />, { "/value/book": book() });
    expect(await screen.findByRole("heading", { name: "Value book" })).toBeInTheDocument();
    expect(screen.getByText("Buy 20 AAPL")).toBeInTheDocument();
  });
});
