import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ValueWaiting } from "./ValueWaiting";

afterEach(cleanup);

const proposal = (id: number, over: Record<string, unknown> = {}) => ({
  id, kind: "buy", symbol: "GOOGL", list_name: "quality_growth", shares: 10, price: 180, cost_usd: 1800,
  reason: "tranche 1", cause: "python", needs_tap: true, status: "pending", fingerprint: `fp${id}`,
  created_at: "2026-11-05T14:00:00Z", expires_at: "2099-01-01T00:00:00Z", ...over,
});
const book = (proposals: unknown[], over: Record<string, unknown> = {}) => ({
  as_of: "2026-11-05T15:00:00Z", available: true, enabled: true, ceiling_usd: 30000, used_usd: 0, positions: [],
  proposals, funding: [], release_max_closes: 2, drain_healthy: true, drain_last_seen: null, ...over,
});

async function bookRead() {
  await waitFor(() => expect(apiFetchMock.mock.calls.length).toBeGreaterThan(0));
  await new Promise((r) => setTimeout(r, 20));
}

describe("ValueWaiting", () => {
  it("lists a waiting buy as a row that jumps to the Value card, not as a second decide flow", async () => {
    renderWithQuery(<ValueWaiting />, { "/value/book": book([proposal(1)]) });
    const row = await screen.findByRole("article");
    expect(row).toHaveTextContent("Value book");
    expect(row).toHaveTextContent("Buy 10 GOOGL");
    expect(row).toHaveTextContent("$1,800.00");
    expect(row).toHaveTextContent(/expires in \d+d/);
    const link = screen.getByRole("link", { name: "Review in the Value book" });
    expect(link.getAttribute("href")?.endsWith("#value-title")).toBe(true);
    // Review Focus 5: one decide flow per value proposal, and it lives on the Value card.
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("button", { name: /Approve|Reject|Review/ })).toBeNull();
  });
  it("says a sale sells at the next check and never invents a cost", async () => {
    renderWithQuery(<ValueWaiting />, { "/value/book": book([proposal(2, { kind: "sell", cost_usd: null, price: null })]) });
    const row = await screen.findByRole("article");
    expect(row).toHaveTextContent("Sell 10 GOOGL");
    expect(row).toHaveTextContent("sells at the next check");
  });
  it("shows a hatched n/a when a buy's cost is unknown", async () => {
    renderWithQuery(<ValueWaiting />, { "/value/book": book([proposal(3, { cost_usd: null })]) });
    const na = await screen.findByText("n/a");
    expect(na.className).toContain("hatch");
  });
  it("does not list a proposal that needs no tap or has been decided", async () => {
    renderWithQuery(<ValueWaiting />, {
      "/value/book": book([proposal(1, { needs_tap: false }), proposal(2, { status: "approved" })]),
    });
    await bookRead();
    expect(screen.queryByRole("article")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("lists every waiting proposal in the book's order", async () => {
    renderWithQuery(<ValueWaiting />, { "/value/book": book([proposal(1), proposal(2, { symbol: "AAPL" })]) });
    const rows = await screen.findAllByRole("article");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Buy 10 GOOGL");
    expect(rows[1]).toHaveTextContent("Buy 10 AAPL");
  });
  it("says a proposal may be waiting when the book could not be read (unknown is not none)", async () => {
    renderWithQuery(<ValueWaiting />, {});
    expect(
      await screen.findByText("The value book could not be read, so a value proposal may be waiting."),
    ).toBeInTheDocument();
  });
  it("says the same when the book is on but its file cannot be read", async () => {
    renderWithQuery(<ValueWaiting />, { "/value/book": book([], { available: false, enabled: true }) });
    expect(
      await screen.findByText("The value book could not be read, so a value proposal may be waiting."),
    ).toBeInTheDocument();
  });
  it("renders nothing when the book was read and nothing waits, or the book is off and never wrote", async () => {
    renderWithQuery(<ValueWaiting />, { "/value/book": book([]) });
    await bookRead();
    expect(screen.queryByRole("article")).toBeNull();
    expect(screen.queryByText(/could not be read/)).toBeNull();
    cleanup();
    renderWithQuery(<ValueWaiting />, { "/value/book": book([], { available: false, enabled: false }) });
    await bookRead();
    expect(screen.queryByText(/could not be read/)).toBeNull();
  });
  it("says there is nothing to decide, in the words it is given, once the book has been read", async () => {
    renderWithQuery(<ValueWaiting emptyText="No value proposal waits on you." />, { "/value/book": book([]) });
    expect(await screen.findByText("No value proposal waits on you.")).toBeInTheDocument();
  });
});
