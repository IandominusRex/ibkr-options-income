import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import type { CommandStatus } from "@/lib/commands";
import { UniverseList } from "./UniverseList";
import { AddSymbol } from "./AddSymbol";
import type { UniverseListOut } from "./types";

const submitUniverseCommand = vi.fn();
vi.mock("@/lib/commands", async () => {
  const actual = await vi.importActual("@/lib/commands");
  return {
    ...(actual as object),
    submitUniverseCommand: (...args: unknown[]) => submitUniverseCommand(...args),
  };
});

afterEach(cleanup);
afterEach(() => {
  submitUniverseCommand.mockReset();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  vi.unstubAllGlobals();
});

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function list(overrides: Partial<UniverseListOut> = {}): UniverseListOut {
  return {
    name: "watchlist",
    overridable: true,
    entries: [],
    ...overrides,
  };
}

function command(overrides: Partial<CommandStatus> = {}): CommandStatus & { created: boolean } {
  return {
    id: 99,
    kind: "universe_remove",
    status: "pending",
    result: null,
    needs_confirmation: false,
    confirm_token: null,
    created_at: "2026-09-07T10:00:00Z",
    applied_at: null,
    as_of: "2026-09-07T10:00:00Z",
    created: true,
    ...overrides,
  };
}

/** Resolves `/research/search` with `hits`; any other path (e.g. the real
 * `useCommandStatus` polling `/commands/{id}`) gets a harmless pending stub -
 * the tests that care about the polled shape assert on what
 * `submitUniverseCommand` itself returned. */
function stubFetch(hits: { symbol: string; name: string; exchange: string | null; is_etf: boolean }[] = []) {
  const fn = vi.fn(async (url: unknown) => {
    const path = String(url);
    if (path.includes("/research/search")) {
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        text: async () => "",
        json: async () => ({ as_of: "x", query: "x", results: hits }),
      };
    }
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      text: async () => "",
      json: async () => command({ status: "pending" }),
    };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** Resolves every fetch (in practice, only `/commands/{id}`) with `status`. */
function stubFetchForCommand(status: CommandStatus) {
  const fn = vi.fn(async () => ({
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => "",
    json: async () => status,
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("UniverseList — controls only render on overridable sections", () => {
  it("renders no add or remove control on the indexes section, plus a read-only note", () => {
    withClient(
      <UniverseList
        list={list({ name: "indexes", overridable: false, entries: [{ symbol: "SPY", overridden: false, removed: false, created_by: null, created_at: null }] })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByTestId("readonly-note-indexes").textContent).toMatch(
      /config\/universe\.yaml/,
    );
    // The symbol itself still renders.
    expect(screen.getByText("SPY")).toBeDefined();
  });

  it("renders no add or remove control on the actively_wheeling section, plus a read-only note", () => {
    withClient(
      <UniverseList
        list={list({
          name: "actively_wheeling",
          overridable: false,
          entries: [{ symbol: "NVDA", overridden: false, removed: false, created_by: null, created_at: null }],
        })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByTestId("readonly-note-actively_wheeling").textContent).toMatch(
      /config\/universe\.yaml/,
    );
  });

  it("renders a plain Remove control for a base (not overridden) entry on an overridable list", () => {
    withClient(
      <UniverseList
        list={list({
          name: "would_own",
          overridable: true,
          entries: [{ symbol: "AAPL", overridden: false, removed: false, created_by: null, created_at: null }],
        })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    expect(screen.getByTestId("remove-AAPL")).toBeDefined();
    // No override badge for a plain, un-overridden entry.
    expect(screen.queryByTestId("override-badge")).toBeNull();
  });

  it("renders the AddSymbol control below the entries on an overridable list, and not on a non-overridable one", () => {
    withClient(
      <UniverseList
        list={list({ name: "watchlist", overridable: true, entries: [] })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    expect(screen.getByTestId("add-symbol-watchlist")).toBeDefined();

    cleanup();

    withClient(
      <UniverseList
        list={list({ name: "indexes", overridable: false, entries: [] })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    expect(screen.queryByTestId("add-symbol-indexes")).toBeNull();
  });
});

describe("AddSymbol — the two confirmation flows differ (spec §9.3)", () => {
  it("adding to would_own opens a confirmation naming cash-secured puts and assignment, before any request", async () => {
    stubFetch([{ symbol: "MSFT", name: "Microsoft", exchange: "NASDAQ", is_etf: false }]);
    withClient(<AddSymbol listName="would_own" />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "MSFT" } });
    const hit = await screen.findByRole("button", { name: /MSFT/i });
    fireEvent.click(hit);

    const dialog = await screen.findByRole("dialog");
    expect(submitUniverseCommand).not.toHaveBeenCalled();
    const summary = dialog.textContent ?? "";
    expect(summary).toMatch(/cash-secured puts/i);
    expect(summary).toMatch(/assign/i);
    expect(summary).toContain("MSFT");
  });

  it("adding to watchlist fires immediately with no dialog", async () => {
    stubFetch([{ symbol: "MSFT", name: "Microsoft", exchange: "NASDAQ", is_etf: false }]);
    submitUniverseCommand.mockResolvedValueOnce(command({ id: 55, kind: "universe_add" }));
    withClient(<AddSymbol listName="watchlist" />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "MSFT" } });
    const hit = await screen.findByRole("button", { name: /MSFT/i });
    fireEvent.click(hit);

    await waitFor(() => expect(submitUniverseCommand).toHaveBeenCalledTimes(1));
    expect(submitUniverseCommand).toHaveBeenCalledWith("add", "watchlist", "MSFT");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("confirming the would_own dialog then fires the add exactly once", async () => {
    stubFetch([{ symbol: "MSFT", name: "Microsoft", exchange: "NASDAQ", is_etf: false }]);
    submitUniverseCommand.mockResolvedValueOnce(command({ id: 56, kind: "universe_add" }));
    withClient(<AddSymbol listName="would_own" />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "MSFT" } });
    const hit = await screen.findByRole("button", { name: /MSFT/i });
    fireEvent.click(hit);

    const dialog = await screen.findByRole("dialog");
    const buttons = dialog.querySelectorAll<HTMLButtonElement>("button");
    fireEvent.click(buttons[buttons.length - 1]); // confirm is last

    await waitFor(() => expect(submitUniverseCommand).toHaveBeenCalledTimes(1));
    expect(submitUniverseCommand).toHaveBeenCalledWith("add", "would_own", "MSFT");
    expect(await screen.findByTestId("command-receipt")).toBeDefined();
  });
});

describe("UniverseList — an overridden entry's badge and visibility", () => {
  it("renders OverrideBadge with author and timestamp plus a revert control; the symbol stays visible whether removed is true or false", () => {
    withClient(
      <UniverseList
        list={list({
          name: "would_own",
          overridable: true,
          entries: [
            { symbol: "TSLA", overridden: true, removed: false, created_by: "ian", created_at: "2026-09-01T10:00:00Z" },
            { symbol: "COIN", overridden: true, removed: true, created_by: "jane", created_at: "2026-08-01T10:00:00Z" },
          ],
        })}
        sectors={{}}
        strikeBands={{}}
      />,
    );

    // Both symbols are present - the removed one is greyed out, not hidden.
    const tslaLink = screen.getByRole("link", { name: "TSLA" });
    const coinLink = screen.getByRole("link", { name: "COIN" });
    expect(tslaLink).toBeDefined();
    expect(coinLink).toBeDefined();
    expect(coinLink.className).toMatch(/line-through/);
    expect(coinLink.className).toMatch(/text-muted/);
    expect(tslaLink.className).not.toMatch(/line-through/);

    const badges = screen.getAllByTestId("override-badge");
    expect(badges).toHaveLength(2);
    expect(badges.map((b) => b.textContent).join(" ")).toContain("ian");
    expect(badges.map((b) => b.textContent).join(" ")).toContain("jane");

    const revertButtons = screen.getAllByTestId("revert-button");
    expect(revertButtons).toHaveLength(2);
  });

  it("clicking revert on a removed entry fires an add (bringing it back)", async () => {
    submitUniverseCommand.mockResolvedValueOnce(command({ id: 61, kind: "universe_add" }));
    withClient(
      <UniverseList
        list={list({
          name: "would_own",
          overridable: true,
          entries: [
            { symbol: "COIN", overridden: true, removed: true, created_by: "jane", created_at: "2026-08-01T10:00:00Z" },
          ],
        })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    fireEvent.click(screen.getByTestId("revert-button"));
    await waitFor(() => expect(submitUniverseCommand).toHaveBeenCalledWith("add", "would_own", "COIN"));
  });

  it("clicking revert on a kept (not removed) override fires a remove", async () => {
    submitUniverseCommand.mockResolvedValueOnce(command({ id: 62, kind: "universe_remove" }));
    withClient(
      <UniverseList
        list={list({
          name: "watchlist",
          overridable: true,
          entries: [
            { symbol: "TSLA", overridden: true, removed: false, created_by: "ian", created_at: "2026-09-01T10:00:00Z" },
          ],
        })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    fireEvent.click(screen.getByTestId("revert-button"));
    await waitFor(() => expect(submitUniverseCommand).toHaveBeenCalledWith("remove", "watchlist", "TSLA"));
  });
});

describe("UniverseList — would_own entries are tagged wheeling vs dip-watch", () => {
  it("tags a would_own symbol also in actively_wheeling as wheeling, and one not in it as dip-watch", () => {
    withClient(
      <UniverseList
        list={list({
          name: "would_own",
          overridable: true,
          entries: [
            { symbol: "NVDA", overridden: false, removed: false, created_by: null, created_at: null },
            { symbol: "AAPL", overridden: false, removed: false, created_by: null, created_at: null },
          ],
        })}
        sectors={{}}
        strikeBands={{}}
        activelyWheeling={new Set(["NVDA"])}
      />,
    );

    const wheelingTag = screen.getByTestId("wheeling-tag-NVDA");
    expect(wheelingTag.textContent).toBe("wheeling");
    expect(wheelingTag.className).toMatch(/text-content/);
    expect(screen.queryByTestId("dip-watch-tag-NVDA")).toBeNull();

    const dipWatchTag = screen.getByTestId("dip-watch-tag-AAPL");
    expect(dipWatchTag.textContent).toBe("dip-watch");
    expect(dipWatchTag.className).toMatch(/text-muted/);
    expect(screen.queryByTestId("wheeling-tag-AAPL")).toBeNull();
  });

  it("does not tag a removed would_own entry as wheeling or dip-watch", () => {
    withClient(
      <UniverseList
        list={list({
          name: "would_own",
          overridable: true,
          entries: [
            { symbol: "COIN", overridden: true, removed: true, created_by: "jane", created_at: "2026-08-01T10:00:00Z" },
          ],
        })}
        sectors={{}}
        strikeBands={{}}
        activelyWheeling={new Set(["COIN"])}
      />,
    );

    expect(screen.queryByTestId("wheeling-tag-COIN")).toBeNull();
    expect(screen.queryByTestId("dip-watch-tag-COIN")).toBeNull();
  });

  it("does not tag entries on a non-would_own list even when activelyWheeling is passed", () => {
    withClient(
      <UniverseList
        list={list({
          name: "watchlist",
          overridable: true,
          entries: [
            { symbol: "NVDA", overridden: false, removed: false, created_by: null, created_at: null },
          ],
        })}
        sectors={{}}
        strikeBands={{}}
        activelyWheeling={new Set(["NVDA"])}
      />,
    );

    expect(screen.queryByTestId("wheeling-tag-NVDA")).toBeNull();
    expect(screen.queryByTestId("dip-watch-tag-NVDA")).toBeNull();
  });
});

describe("UniverseList — every mutation renders a CommandReceipt and polling stops at a terminal state", () => {
  it("renders a receipt after Remove, and issues no further /commands poll once the command is applied", async () => {
    submitUniverseCommand.mockResolvedValueOnce(command({ id: 99, status: "pending" }));
    const fetchMock = stubFetchForCommand(command({ id: 99, status: "applied", applied_at: "x" }));

    withClient(
      <UniverseList
        list={list({
          name: "would_own",
          overridable: true,
          entries: [{ symbol: "AAPL", overridden: false, removed: false, created_by: null, created_at: null }],
        })}
        sectors={{}}
        strikeBands={{}}
      />,
    );

    fireEvent.click(screen.getByTestId("remove-AAPL"));

    await waitFor(() => {
      const receipt = screen.getByTestId("command-receipt");
      expect(receipt.getAttribute("data-state")).toBe("applied");
    });
    expect(screen.getByText(/intent 99/)).toBeDefined();

    const callsAfterSettling = fetchMock.mock.calls.length;
    expect(callsAfterSettling).toBeGreaterThan(0);

    // Wait past the 2s poll interval. If the hook kept polling after a
    // terminal state, this call count would grow.
    await new Promise((r) => setTimeout(r, 2300));
    expect(fetchMock.mock.calls.length).toBe(callsAfterSettling);
  }, 8000);

  it("a 403 on remove renders a permission message, not a generic failure", async () => {
    submitUniverseCommand.mockRejectedValueOnce(new ApiError(403, "forbidden"));
    withClient(
      <UniverseList
        list={list({
          name: "would_own",
          overridable: true,
          entries: [{ symbol: "AAPL", overridden: false, removed: false, created_by: null, created_at: null }],
        })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    fireEvent.click(screen.getByTestId("remove-AAPL"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("permission");
  });

  it("a 409 (actively_wheeling) on remove is handled gracefully with a specific message", async () => {
    submitUniverseCommand.mockRejectedValueOnce(
      new ApiError(409, JSON.stringify({ reason: "actively_wheeling", symbol: "AAPL" })),
    );
    withClient(
      <UniverseList
        list={list({
          name: "would_own",
          overridable: true,
          entries: [{ symbol: "AAPL", overridden: false, removed: false, created_by: null, created_at: null }],
        })}
        sectors={{}}
        strikeBands={{}}
      />,
    );
    fireEvent.click(screen.getByTestId("remove-AAPL"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/actively wheeled/i);
  });
});

describe("No em dashes anywhere in the rendered copy", () => {
  it("UniverseList with overridden and removed entries, plus the read-only note, carries no em dash", () => {
    const { container } = withClient(
      <>
        <UniverseList
          list={list({
            name: "would_own",
            overridable: true,
            entries: [
              { symbol: "TSLA", overridden: true, removed: false, created_by: "ian", created_at: "2026-09-01T10:00:00Z" },
              { symbol: "COIN", overridden: true, removed: true, created_by: "jane", created_at: "2026-08-01T10:00:00Z" },
              { symbol: "AAPL", overridden: false, removed: false, created_by: null, created_at: null },
            ],
          })}
          sectors={{ TSLA: "auto" }}
          strikeBands={{ AAPL: 1.5 }}
        />
        <UniverseList
          list={list({
            name: "indexes",
            overridable: false,
            entries: [{ symbol: "SPY", overridden: false, removed: false, created_by: null, created_at: null }],
          })}
          sectors={{}}
          strikeBands={{}}
        />
      </>,
    );
    expect(container.textContent).not.toContain("—");
  });

  it("the would_own AddSymbol confirmation dialog carries no em dash", async () => {
    stubFetch([{ symbol: "MSFT", name: "Microsoft", exchange: "NASDAQ", is_etf: false }]);
    withClient(<AddSymbol listName="would_own" />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "MSFT" } });
    const hit = await screen.findByRole("button", { name: /MSFT/i });
    fireEvent.click(hit);
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).not.toContain("—");
  });
});
