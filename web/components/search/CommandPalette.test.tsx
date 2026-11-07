import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { apiFetch } from "@/lib/api";
import { openSearch } from "@/lib/search";
import { CommandPalette } from "./CommandPalette";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(async (path: string) => ({
    as_of: "2026-09-02T00:00:00Z",
    query: path,
    results: path.includes("q=AAP")
      ? [
          { symbol: "AAP", name: "Advance Auto Parts", exchange: "NYSE", is_etf: false },
          { symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false },
        ]
      : path.includes("q=SPY")
        ? [{ symbol: "SPY", name: "SPDR S&P 500 ETF", exchange: "NYSE Arca", is_etf: true }]
        : [],
  })),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const input = () => screen.getByRole("combobox", { name: "Search a ticker, company or page" });

function openWithShortcut() {
  fireEvent.keyDown(window, { key: "k", metaKey: true });
}

describe("CommandPalette", () => {
  beforeEach(() => push.mockClear());

  it("is closed until the shortcut fires", () => {
    render(<CommandPalette />);
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
  });

  it("opens on meta+k and on ctrl+k", () => {
    const { unmount } = render(<CommandPalette />);
    openWithShortcut();
    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
    unmount();
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
  });

  it("opens when anything calls openSearch(), so the rail, More and Research reach this one dialog", () => {
    render(<CommandPalette />);
    act(() => openSearch());
    expect(input()).toHaveFocus();
  });

  it("shows ticker results and navigates on select", async () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "AAP" } });
    await waitFor(() => expect(screen.getByText("Apple Inc.")).toBeDefined());
    fireEvent.click(screen.getByText("Apple Inc."));
    expect(push).toHaveBeenCalledWith("/stock/AAPL");
  });

  it("lists the console's pages above the tickers, and opens a page", async () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "trades" } });
    const pages = screen.getByRole("group", { name: "Pages" });
    expect(pages).toHaveTextContent("Trades");
    fireEvent.click(screen.getAllByRole("option")[0]!);
    expect(push).toHaveBeenCalledWith("/trades");
  });

  it("marks an ETF in words", async () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "SPY" } });
    expect(await screen.findByText("ETF")).toBeInTheDocument();
  });

  it("moves through the results with the arrow keys and opens the active one with Enter", async () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "AAP" } });
    await screen.findByText("Apple Inc.");
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(input()).toHaveAttribute("aria-activedescendant", options[0]!.id);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(input()).toHaveAttribute("aria-activedescendant", options[1]!.id);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(input()).toHaveAttribute("aria-activedescendant", options[0]!.id);
    fireEvent.keyDown(input(), { key: "ArrowUp" });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/stock/AAPL");
  });

  it("says nothing matches only once the search has answered", async () => {
    render(<CommandPalette />);
    openWithShortcut();
    expect(screen.getByRole("status")).toHaveTextContent("Type a ticker, a company or a page.");
    fireEvent.change(input(), { target: { value: "zzzz" } });
    expect(screen.getByRole("status")).not.toHaveTextContent("No ticker or page matches");
    expect(await screen.findByText('No ticker or page matches "zzzz".')).toBeInTheDocument();
  });

  it("says the tickers are being searched while the answer is pending and no page matches", async () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "zzzz" } });
    expect(screen.getByRole("status")).toHaveTextContent("Searching tickers.");
    expect(await screen.findByText('No ticker or page matches "zzzz".')).toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent("Searching tickers.");
  });

  it("says the ticker search failed in words, and still lists the pages", async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error("down"));
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "news" } });
    expect(await screen.findByText("Tickers could not be searched right now.")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Pages" })).toHaveTextContent("News");
  });

  it("closes on a tap on the scrim and on Close, which a phone has instead of Escape", () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.mouseDown(screen.getByTestId("search-scrim"));
    expect(screen.queryByRole("dialog")).toBeNull();
    openWithShortcut();
    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders as a labelled dialog", () => {
    render(<CommandPalette />);
    openWithShortcut();
    const dialog = screen.getByRole("dialog", { name: "Search the console" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });

  it("clears the search term and results on reopen, not stale from last time", async () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "AAP" } });
    await waitFor(() => expect(screen.getByText("Apple Inc.")).toBeDefined());

    fireEvent.keyDown(window, { key: "Escape" });
    openWithShortcut();

    expect((input() as HTMLInputElement).value).toBe("");
    expect(screen.queryByText("Apple Inc.")).toBeNull();
  });

  it("returns focus to whatever had it when the palette opened, once it closes", () => {
    render(
      <div>
        <button>Trigger</button>
        <CommandPalette />
      </div>,
    );
    const trigger = screen.getByRole("button", { name: "Trigger" });
    trigger.focus();
    openWithShortcut();
    expect(input()).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.activeElement).toBe(trigger);
  });

  it("carries no em dash in what it says", async () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "zzzz" } });
    await screen.findByText('No ticker or page matches "zzzz".');
    expect(screen.getByRole("dialog").textContent).not.toContain("—");
  });
});

describe("CommandPalette, review fixes", () => {
  beforeEach(() => push.mockClear());

  /** jsdom has no layout, so model `md:hidden` (display:none from 768px): an element with that class has no boxes. */
  function modelDesktopLayout() {
    const spy = vi
      .spyOn(HTMLElement.prototype, "getClientRects")
      .mockImplementation(function (this: HTMLElement) {
        return (this.classList.contains("md:hidden") ? [] : [{}]) as unknown as DOMRectList;
      });
    return () => spy.mockRestore();
  }

  it("keeps Tab inside the dialog on a desktop, where Close is hidden and the input is the only stop", () => {
    const restore = modelDesktopLayout();
    try {
      render(<CommandPalette />);
      openWithShortcut();
      input().focus();
      expect(fireEvent.keyDown(document, { key: "Tab" })).toBe(false);
      expect(fireEvent.keyDown(document, { key: "Tab", shiftKey: true })).toBe(false);
    } finally {
      restore();
    }
  });

  it("keeps a late older ticker answer from clearing the newer one", async () => {
    type Resolve = (v: unknown) => void;
    let resolveOld: Resolve = () => {};
    let resolveNew: Resolve = () => {};
    vi.mocked(apiFetch)
      .mockImplementationOnce(() => new Promise((r) => (resolveOld = r)))
      .mockImplementationOnce(() => new Promise((r) => (resolveNew = r)));
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "AAP" } });
    await waitFor(() => expect(apiFetch).toHaveBeenLastCalledWith("/research/search?q=AAP"));
    fireEvent.change(input(), { target: { value: "SPY" } });
    await waitFor(() => expect(apiFetch).toHaveBeenLastCalledWith("/research/search?q=SPY"));
    await act(async () => {
      resolveNew({
        as_of: "x",
        query: "SPY",
        results: [{ symbol: "SPY", name: "SPDR S&P 500 ETF", exchange: "NYSE Arca", is_etf: true }],
      });
    });
    expect(await screen.findByText("SPDR S&P 500 ETF")).toBeInTheDocument();
    await act(async () => {
      resolveOld({ as_of: "x", query: "AAP", results: [] });
    });
    expect(screen.getByText("SPDR S&P 500 ETF")).toBeInTheDocument();
  });

  it("does not open the highlighted result when Enter confirms an IME composition", () => {
    render(<CommandPalette />);
    openWithShortcut();
    fireEvent.change(input(), { target: { value: "trades" } });
    fireEvent.keyDown(input(), { key: "Enter", isComposing: true });
    expect(push).not.toHaveBeenCalled();
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/trades");
  });
});

describe("CommandPalette, controlled open", () => {
  it("renders open when the open prop is true, with no shortcut needed", () => {
    render(<CommandPalette open onOpenChange={() => {}} />);
    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
  });

  it("stays closed when the open prop is false", () => {
    render(<CommandPalette open={false} onOpenChange={() => {}} />);
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
  });

  it("calls onOpenChange(false) on Escape rather than managing its own state", () => {
    const onOpenChange = vi.fn();
    render(<CommandPalette open onOpenChange={onOpenChange} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
