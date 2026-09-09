import { describe, it, expect, vi, afterEach } from "vitest";

import { ApiError, apiFetch } from "./api";

// apiFetch is the single choke point for every backend call from the browser.
// The two empty-body routes are watchlist remove (DELETE 204) and the
// live-mode second confirmation (POST /commands/{id}/confirm -> 204).

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses a JSON body on 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [] }), { status: 200 }),
      ),
    );

    const out = await apiFetch<{ items: unknown[] }>("/watchlist");
    expect(out.items).toEqual([]);
  });

  it("returns undefined for 204 No Content without throwing", async () => {
    // Regression: an unconditional res.json() throws SyntaxError on a 204,
    // so a *successful* watchlist remove surfaced as a client-side error.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );

    const out = await apiFetch<void>("/watchlist/AAPL", { method: "DELETE" });
    expect(out).toBeUndefined();
  });

  it("throws ApiError with the server detail on a non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        async () =>
          new Response(JSON.stringify({ detail: "nope" }), { status: 404 }),
      ),
    );

    await expect(apiFetch("/unknown")).rejects.toThrow(ApiError);
    await expect(apiFetch("/unknown")).rejects.toMatchObject({
      status: 404,
      message: JSON.stringify({ detail: "nope" }),
    });
  });
});