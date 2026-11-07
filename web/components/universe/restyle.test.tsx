import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { AddSymbol } from "./AddSymbol";
import { OverrideBadge } from "./OverrideBadge";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));

// Web overhaul Part 6 restyled the universe controls in place; UniverseList.test.tsx keeps their behaviour.
function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("AddSymbol, restyled", () => {
  it("is named by a visible label, on the console's 44px field", () => {
    withClient(<AddSymbol listName="would_own" />);
    const input = screen.getByRole("textbox", { name: "Add a name to Would own" });
    expect(input).toHaveClass("min-h-11");
  });

  it("says a failed ticker search in words, not 'no ticker matches'", async () => {
    const { apiFetch } = await import("@/lib/api");
    vi.mocked(apiFetch).mockRejectedValue(new Error("down"));
    withClient(<AddSymbol listName="watchlist" />);
    fireEvent.change(screen.getByRole("textbox", { name: "Add a name to Watchlist" }), { target: { value: "AAP" } });
    expect(await screen.findByText("Tickers could not be searched right now.")).toBeInTheDocument();
    expect(screen.queryByText("No ticker matches yet.")).toBeNull();
  });

  it("names the Watchlist in its label", () => {
    withClient(<AddSymbol listName="watchlist" />);
    expect(screen.getByRole("textbox", { name: "Add a name to Watchlist" })).toBeInTheDocument();
  });
});

describe("OverrideBadge, restyled", () => {
  it("makes Revert a 44px target on a phone and hatches an unknown author", () => {
    const onRevert = vi.fn();
    render(<OverrideBadge author={null} timestamp={null} removed={false} onRevert={onRevert} />);
    const revert = screen.getByRole("button", { name: "Revert" });
    expect(revert).toHaveClass("min-h-11", "md:min-h-0");
    for (const na of screen.getAllByText("n/a")) expect(na).toHaveClass("hatch");
    fireEvent.click(revert);
    expect(onRevert).toHaveBeenCalledTimes(1);
  });

  it("hatches an unknown time too, so a known author never hides it", () => {
    render(<OverrideBadge author="ian" timestamp={null} removed={false} onRevert={() => {}} />);
    expect(screen.getByText("n/a")).toHaveClass("hatch");
    expect(screen.getByTestId("override-badge")).toHaveTextContent("added by ian · n/a");
  });
});
