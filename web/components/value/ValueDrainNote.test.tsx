import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ValueDrainNote } from "./ValueDrainNote";
import type { ValueBook } from "./types";

afterEach(cleanup);

function book(over: Partial<ValueBook>): ValueBook {
  return {
    as_of: "2026-11-05T15:00:00Z", available: true, enabled: true, ceiling_usd: 30000, used_usd: 0,
    positions: [], proposals: [], funding: [],
    breakers: { trend: false, drawdown: false, drawdown_pct: 0, trim_offered: false, trim_episode: null, trimmed: false },
    release_max_closes: 2, drain_healthy: true, drain_last_seen: "2026-11-05T14:59:30Z", ...over,
  };
}

/** The book request is awaited before asserting on silence, so "nothing" is not just "not loaded yet". */
async function bookRead() {
  await waitFor(() => expect(apiFetchMock.mock.calls.length).toBeGreaterThan(0));
  await new Promise((r) => setTimeout(r, 20));
}

describe("ValueDrainNote", () => {
  it("renders nothing while the value process is checking for taps", async () => {
    renderWithQuery(<ValueDrainNote pending />, { "/value/book": book({ drain_healthy: true }) });
    await bookRead();
    expect(screen.queryByTestId("value-drain-note")).toBeNull();
  });

  it("says Not checking and when the value process last checked, in New York time", async () => {
    renderWithQuery(<ValueDrainNote pending />, {
      "/value/book": book({ drain_healthy: false, drain_last_seen: "2026-11-05T19:31:00Z" }),
    });
    const note = await screen.findByTestId("value-drain-note");
    expect(note).toHaveTextContent("Not checking");
    expect(note).toHaveTextContent("last checked for taps");
    expect(note).toHaveTextContent("2:31 PM ET");
    expect(note).toHaveTextContent("This tap waits until it checks again.");
  });

  it("says the process has not checked yet when it never has", async () => {
    renderWithQuery(<ValueDrainNote pending />, {
      "/value/book": book({ drain_healthy: false, drain_last_seen: null }),
    });
    const note = await screen.findByTestId("value-drain-note");
    expect(note).toHaveTextContent("Not checking");
    expect(note).toHaveTextContent("has not checked for taps yet");
    expect(note).toHaveTextContent("This tap waits until it runs.");
  });

  it("renders nothing once the command is no longer pending, even if the process is stale", async () => {
    renderWithQuery(<ValueDrainNote pending={false} />, {
      "/value/book": book({ drain_healthy: false, drain_last_seen: "2026-11-05T19:31:00Z" }),
    });
    await bookRead();
    expect(screen.queryByTestId("value-drain-note")).toBeNull();
  });

  it("renders nothing when the book could not be read (unknown is not stalled)", async () => {
    renderWithQuery(<ValueDrainNote pending />, {});
    await bookRead();
    expect(screen.queryByTestId("value-drain-note")).toBeNull();
  });
});
