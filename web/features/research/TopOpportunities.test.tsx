import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { TopOpportunities } from "./TopOpportunities";
import type { AssessedResponse, TopItem, TopResponse } from "./types";

afterEach(cleanup);
beforeEach(() => {
  (apiFetchMock as unknown as { mockClear: () => void }).mockClear();
});

function item(symbol: string, over: Partial<TopItem> = {}): TopItem {
  return {
    symbol,
    list_name: "deep_value",
    verdict: "READY",
    decided_by: "python",
    price: 100,
    fair_value: 140,
    entry_ceiling: 105,
    stop: null,
    half_sell: 140,
    mos: 0.28,
    reasons: ["healthy, cheap enough, timing passes"],
    put_ceiling: null,
    age_days: 1,
    ...over,
  };
}

function top(list: TopResponse["list_name"], items: TopItem[], available = true): TopResponse {
  return { as_of: "2026-11-05T15:00:00Z", available, list_name: list, items };
}

const NO_ASSESSED: AssessedResponse = { as_of: "x", run_id: "r1", computed_at: null, groups: [] };

function passedCsp(symbol: string, strike: number): AssessedResponse {
  return {
    as_of: "x",
    run_id: "r1",
    computed_at: null,
    groups: [
      {
        as_of: "x",
        symbol,
        counts: {},
        contracts: [
          {
            as_of: "x", candidate_id: "c1", symbol, strategy: "cash_secured_put", strike, expiry: null, stage: "passed",
            reasons: [], reasons_text: [], blended_score: 0.7, premium: 2, ideal: null, promotable: true, promote_note: null,
          },
        ],
      },
    ],
  };
}

function paths(): string[] {
  return apiFetchMock.mock.calls.map((c) => String(c[0]));
}

describe("TopOpportunities", () => {
  it("has two tabs, Deep value first, and asks for the list on view", async () => {
    renderWithQuery(<TopOpportunities />, {
      "/value/top?list=deep_value": top("deep_value", [item("GOOGL")]),
      "/value/top?list=quality_growth": top("quality_growth", [item("MSFT", { list_name: "quality_growth" })]),
    });
    const tabs = screen.getByRole("group", { name: "Opportunity list" });
    const buttons = within(tabs).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Deep value", "Quality growth"]);
    expect(buttons[0]!.getAttribute("aria-pressed")).toBe("true");
    expect(await screen.findByRole("article", { name: /GOOGL/ })).toBeTruthy();
    expect(paths().some((p) => p.includes("quality_growth"))).toBe(false);

    fireEvent.click(buttons[1]!);
    expect(await screen.findByRole("article", { name: /MSFT/ })).toBeTruthy();
    expect(screen.queryByRole("article", { name: /GOOGL/ })).toBeNull();
  });

  it("shows at most ten cards, READY first", async () => {
    const rows = [
      item("WAITER", { verdict: "WAIT" }),
      item("WATCHER", { verdict: "WATCH" }),
      ...Array.from({ length: 9 }, (_, i) => item(`R${i}`)),
    ];
    renderWithQuery(<TopOpportunities />, { "/value/top?list=deep_value": top("deep_value", rows) });
    await screen.findByRole("article", { name: /R0/ });
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(10);
    expect(within(cards[0]!).getByText("R0")).toBeTruthy();
    expect(within(cards[9]!).getByText("WATCHER")).toBeTruthy();
    expect(screen.queryByRole("article", { name: /WAITER/ })).toBeNull();
  });

  it("says in one sentence that the book has written nothing when the API says unavailable", async () => {
    renderWithQuery(<TopOpportunities />, { "/value/top?list=deep_value": top("deep_value", [], false) });
    expect(await screen.findByText("The value book has not written anything yet.")).toBeTruthy();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("says so when a list has no names, and when the request fails", async () => {
    renderWithQuery(<TopOpportunities />, { "/value/top?list=deep_value": top("deep_value", []) });
    expect(await screen.findByText("No name on the Deep value list is ready, on watch or waiting.")).toBeTruthy();
    cleanup();
    renderWithQuery(<TopOpportunities />, {});
    expect(await screen.findByText("The top opportunities could not be loaded right now.")).toBeTruthy();
  });

  it("offers the put link only for a name with a ceiling and a passed CSP candidate under it", async () => {
    renderWithQuery(<TopOpportunities />, {
      "/value/top?list=deep_value": top("deep_value", [
        item("GOOGL", { put_ceiling: 105 }),
        item("AAPL", { put_ceiling: 95 }),
        item("NOCEIL", { put_ceiling: null }),
      ]),
      "/options/assessed": {
        ...passedCsp("GOOGL", 100),
        groups: [...passedCsp("GOOGL", 100).groups, ...passedCsp("AAPL", 110).groups],
      },
    });
    const googl = await screen.findByRole("article", { name: /GOOGL/ });
    expect(await within(googl).findByRole("link", { name: "Sell a put up to $105.00" })).toBeTruthy();
    expect(within(screen.getByRole("article", { name: /AAPL/ })).queryByRole("link", { name: /Sell a put/ })).toBeNull();
    expect(within(screen.getByRole("article", { name: /NOCEIL/ })).queryByRole("link", { name: /Sell a put/ })).toBeNull();
  });

  it("asks the assessed browser's endpoint once, for passed candidates, and not at all without a ceiling", async () => {
    renderWithQuery(<TopOpportunities />, {
      "/value/top?list=deep_value": top("deep_value", [item("GOOGL", { put_ceiling: 105 })]),
      "/options/assessed": NO_ASSESSED,
    });
    await screen.findByRole("article", { name: /GOOGL/ });
    await waitFor(() => expect(paths().filter((p) => p.startsWith("/options/assessed"))).toHaveLength(1));
    expect(paths().find((p) => p.startsWith("/options/assessed"))).toContain("stage=passed");
    expect(screen.queryByRole("link", { name: /Sell a put/ })).toBeNull();

    cleanup();
    (apiFetchMock as unknown as { mockClear: () => void }).mockClear();
    renderWithQuery(<TopOpportunities />, { "/value/top?list=deep_value": top("deep_value", [item("GOOGL")]) });
    await screen.findByRole("article", { name: /GOOGL/ });
    expect(paths().some((p) => p.startsWith("/options/assessed"))).toBe(false);
  });

  it("keeps the put link off when the assessed request fails", async () => {
    renderWithQuery(<TopOpportunities />, {
      "/value/top?list=deep_value": top("deep_value", [item("GOOGL", { put_ceiling: 105 })]),
    });
    const card = await screen.findByRole("article", { name: /GOOGL/ });
    await waitFor(() => expect(paths().some((p) => p.startsWith("/options/assessed"))).toBe(true));
    expect(within(card).queryByRole("link", { name: /Sell a put/ })).toBeNull();
    expect(within(card).getByRole("link", { name: "See the value file" })).toBeTruthy();
  });

  it("sends no command and shows no button but the two tabs", async () => {
    renderWithQuery(<TopOpportunities />, {
      "/value/top?list=deep_value": top("deep_value", [item("GOOGL", { decided_by: "claude" })]),
    });
    await screen.findByRole("article", { name: /GOOGL/ });
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(apiFetchMock.mock.calls.every((c) => !String(c[0]).startsWith("/commands"))).toBe(true);
    expect(screen.getByText(/Claude's verdict decides this/)).toBeTruthy();
  });
});
