import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { OpportunityCard } from "./OpportunityCard";
import type { TopItem } from "./types";

afterEach(cleanup);

function item(over: Partial<TopItem> = {}): TopItem {
  return {
    symbol: "GOOGL",
    list_name: "deep_value",
    verdict: "READY",
    decided_by: "python",
    price: 182.4,
    fair_value: 215,
    entry_ceiling: 190,
    stop: null,
    half_sell: 215,
    mos: 0.151,
    reasons: ["healthy, cheap enough, timing passes"],
    put_ceiling: 190,
    age_days: 1,
    ...over,
  };
}

describe("OpportunityCard", () => {
  it("names the company, the list, the verdict and who decided it", () => {
    render(<OpportunityCard item={item({ decided_by: "claude" })} canSellPut={false} />);
    const card = screen.getByRole("article", { name: /GOOGL/ });
    expect(within(card).getByText("Deep value")).toBeTruthy();
    expect(within(card).getByText("Ready")).toBeTruthy();
    expect(within(card).getByText(/Claude's verdict decides this/)).toBeTruthy();
    cleanup();
    render(<OpportunityCard item={item()} canSellPut={false} />);
    expect(screen.getByText("Python only")).toBeTruthy();
  });

  it("draws one bar with every known level labelled and its number visible", () => {
    render(<OpportunityCard item={item()} canSellPut={false} />);
    const bar = screen.getByRole("img", { name: /Price \$182\.40/ });
    expect(bar.getAttribute("aria-label")).toMatch(/Fair value \$215\.00/);
    expect(bar.getAttribute("aria-label")).toMatch(/Entry ceiling \$190\.00/);
    expect(within(bar).getByText("$182.40")).toBeTruthy();
    expect(within(bar).getByText("$190.00")).toBeTruthy();
    expect(within(bar).getByText("$215.00")).toBeTruthy();
    expect(within(bar).getByText(/Fair value, half sale/)).toBeTruthy();
  });

  it("shows the stop as a hatched n/a when the API has none, never as a zero", () => {
    render(<OpportunityCard item={item()} canSellPut={false} />);
    const stop = screen.getByText(/Not on the bar/);
    expect(within(stop).getByText("n/a").className).toContain("hatch");
    expect(stop.textContent).toMatch(/Stop/);
    expect(screen.queryByText("$0.00")).toBeNull();
  });

  it("puts the stop on the bar when the API supplies one", () => {
    render(<OpportunityCard item={item({ stop: 140 })} canSellPut={false} />);
    const bar = screen.getByRole("img", { name: /Stop \$140\.00/ });
    expect(within(bar).getByText("$140.00")).toBeTruthy();
    expect(screen.queryByText(/Not on the bar/)).toBeNull();
  });

  it("shows the margin of safety and a hatched n/a when it is unknown", () => {
    render(<OpportunityCard item={item()} canSellPut={false} />);
    expect(screen.getByText("Margin of safety").parentElement?.textContent).toContain("15.1%");
    cleanup();
    render(<OpportunityCard item={item({ mos: null })} canSellPut={false} />);
    const dd = screen.getByText("Margin of safety").parentElement as HTMLElement;
    expect(within(dd).getByText("n/a").className).toContain("hatch");
  });

  it("lists the reasons as Python's, in plain sentences", () => {
    render(
      <OpportunityCard
        item={item({ verdict: "WAIT", reasons: ["price 195.00 above the entry ceiling 190.00"] })}
        canSellPut={false}
      />,
    );
    expect(screen.getByText("Python's reasons")).toBeTruthy();
    expect(screen.getByText("The price, $195.00, is above the entry ceiling, $190.00.")).toBeTruthy();
  });

  it("offers See the value file only on a READY name, and only as a link to the value block", () => {
    render(<OpportunityCard item={item()} canSellPut={false} />);
    const buy = screen.getByRole("link", { name: "See the value file" });
    expect(buy.getAttribute("href")).toBe("/stock/GOOGL#value-block-GOOGL");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    cleanup();
    render(<OpportunityCard item={item({ verdict: "WATCH" })} canSellPut={false} />);
    expect(screen.queryByRole("link", { name: "See the value file" })).toBeNull();
  });

  it("offers the put link only when the parent found a passing CSP", () => {
    render(<OpportunityCard item={item()} canSellPut={false} />);
    expect(screen.queryByRole("link", { name: /Sell a put/ })).toBeNull();
    cleanup();
    render(<OpportunityCard item={item()} canSellPut />);
    const put = screen.getByRole("link", { name: "Sell a put up to $190.00" });
    expect(put.getAttribute("href")).toBe("/trades?view=assessed&strategy=csp&symbol=GOOGL");
  });

  it("states the file's age, or a hatched n/a when unknown", () => {
    render(<OpportunityCard item={item({ age_days: 3 })} canSellPut={false} />);
    expect(screen.getByText("Scorecard 3 days old")).toBeTruthy();
    cleanup();
    render(<OpportunityCard item={item({ age_days: null })} canSellPut={false} />);
    const age = screen.getByText(/^Scorecard/);
    expect(within(age).getByText("n/a").className).toContain("hatch");
  });

  it("shows Claude's one-line note after Python's reasons, labelled as Claude's and never on a link or button", () => {
    render(<OpportunityCard item={item({ claude_note: "Search share is holding; the cloud margin carries the bear case." })} canSellPut />);
    const note = screen.getByText("Search share is holding; the cloud margin carries the bear case.");
    expect(screen.getByText("Claude's note")).toBeTruthy();
    expect(screen.getByText("its reading, not a gate")).toBeTruthy();
    expect(note.closest("a, button")).toBeNull();
    const reasons = screen.getByText("Python's reasons");
    expect(reasons.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows no note, and no empty label, when Claude has not read the name for this list", () => {
    render(<OpportunityCard item={item({ claude_note: null })} canSellPut={false} />);
    expect(screen.queryByText("Claude's note")).toBeNull();
  });
});
