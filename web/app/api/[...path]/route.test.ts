import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Tests for the server-side proxy at app/api/[...path]/route.ts.
// The browser never holds a credential — the proxy injects API_TOKEN server-side.

function req(url: string): Request {
  return new Request(`http://localhost:3000${url}`);
}

function ctx(path: string[]): { params: Promise<{ path: string[] }> } {
  return { params: Promise.resolve({ path }) };
}

describe("API proxy", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    process.env.API_TOKEN = undefined;
    process.env.API_URL = undefined;
  });

  it("injects Authorization: Bearer ${API_TOKEN} server-side", async () => {
    process.env.API_TOKEN = "secret-token";
    process.env.API_URL = "http://upstream.test";

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response("ok", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const { GET } = await import("./route");

    const req = new Request("http://localhost:3000/api/health");
    await GET(req, { params: Promise.resolve({ path: ["health"] }) });

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://upstream.test/health");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer secret-token",
    });
  });

  it("returns 500 with a clear message when API_TOKEN is missing", async () => {
    delete process.env.API_TOKEN;
    process.env.API_URL = "http://upstream.test";

    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const { GET } = await import("./route");

    const req = new Request("http://localhost:3000/api/health");
    const res = await GET(req, { params: Promise.resolve({ path: ["health"] }) });

    expect(res.status).toBe(500);
    expect(fetchSpy).not.toHaveBeenCalled();
    const body = await res.json();
    expect(body.detail).toContain("API_TOKEN");
  });

  it("defaults upstream to http://127.0.0.1:8787", async () => {
    process.env.API_TOKEN = "tok";
    delete process.env.API_URL;

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response("ok", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const { GET } = await import("./route");

    const req = new Request("http://localhost:3000/api/health");
    await GET(req, { params: Promise.resolve({ path: ["health"] }) });

    const [url] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8787/health");
  });

  it("returns 405 for PUT", async () => {
    process.env.API_TOKEN = "tok";
    const { PUT } = await import("./route");
    const req = new Request("http://localhost:3000/api/x", { method: "PUT" });
    const res = await PUT(req, { params: Promise.resolve({ path: ["x"] }) });
    expect(res.status).toBe(405);
  });

  it("returns 405 for PATCH", async () => {
    process.env.API_TOKEN = "tok";
    const { PATCH } = await import("./route");
    const req = new Request("http://localhost:3000/api/x", { method: "PATCH" });
    const res = await PATCH(req, { params: Promise.resolve({ path: ["x"] }) });
    expect(res.status).toBe(405);
  });

  it("returns 405 for HEAD", async () => {
    process.env.API_TOKEN = "tok";
    const { HEAD } = await import("./route");
    const req = new Request("http://localhost:3000/api/x", { method: "HEAD" });
    const res = await HEAD(req, { params: Promise.resolve({ path: ["x"] }) });
    expect(res.status).toBe(405);
  });

  it("passes through the upstream status and body unchanged", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "nope" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { GET } = await import("./route");
    const req = new Request("http://localhost:3000/api/unknown");
    const res = await GET(req, { params: Promise.resolve({ path: ["unknown"] }) });

    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "nope" });
  });

  it("forwards the request body for POST", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const { POST } = await import("./route");
    const body = JSON.stringify({ kind: "refresh", payload: {} });
    const req = new Request("http://localhost:3000/api/commands", {
      method: "POST",
      body,
      headers: { "Content-Type": "application/json" },
    });
    await POST(req, { params: Promise.resolve({ path: ["commands"] }) });

    const [, init] = fetchSpy.mock.calls[0];
    expect((init as RequestInit).method).toBe("POST");
    expect(await new Response((init as RequestInit).body).text()).toBe(body);
  });

  it("forwards the query string (search params survive the proxy)", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    const fetchSpy = vi.fn().mockResolvedValue(
      new Response("[]", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const { GET } = await import("./route");

    // Regression: the catch-all params carry only path segments, so a proxy
    // that rebuilds the target from path.join("/") alone drops ?q=app — the
    // backend's blank-query rule then returns an empty result and the ⌘K
    // palette shows "No match" forever.
    const req = new Request(
      "http://localhost:3000/api/research/search?q=app&limit=5",
    );
    await GET(req, {
      params: Promise.resolve({ path: ["research", "search"] }),
    });

    const [url] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://upstream.test/research/search?q=app&limit=5");
  });

  it("passes a 204 through with a null body, not a 500", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );

    const { DELETE } = await import("./route");

    // Regression: new Response("", { status: 204 }) throws (204 requires a
    // null body), turning a successful live-mode confirm or watchlist remove
    // into a 500 the UI reports as "Nothing was sent".
    const req = new Request("http://localhost:3000/api/watchlist/AAPL", {
      method: "DELETE",
    });
    const res = await DELETE(req, {
      params: Promise.resolve({ path: ["watchlist", "AAPL"] }),
    });

    expect(res.status).toBe(204);
    expect(res.body).toBeNull();
  });

  it("passes a 304 through with a null body", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 304 })),
    );

    const { GET } = await import("./route");
    const req = new Request("http://localhost:3000/api/health");
    const res = await GET(req, { params: Promise.resolve({ path: ["health"] }) });

    expect(res.status).toBe(304);
    expect(res.body).toBeNull();
  });

  it("returns a JSON 502 when the API cannot be reached", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    // Mirrors what Node's fetch actually throws on a refused connection.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    const { GET } = await import("./route");
    const req = new Request("http://localhost:3000/api/portfolio/summary");
    const res = await GET(req, {
      params: Promise.resolve({ path: ["portfolio", "summary"] }),
    });

    expect(res.status).toBe(502);
    expect(res.headers.get("Content-Type")).toContain("application/json");
    const body = await res.json();
    expect(body.detail).toMatch(/not reachable/i);
    // No token, no upstream host/URL, no stack trace — the browser has no
    // business seeing any of those.
    expect(body.detail).not.toMatch(/127\.0\.0\.1|localhost|upstream\.test|Bearer/i);
  });

  it("returns a JSON 504 when the API does not answer in time", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    vi.useFakeTimers();
    try {
      // A realistic hung upstream: the fetch promise never settles on its
      // own, but (like real fetch) rejects once the passed AbortSignal fires.
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
          return new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              reject(
                (init.signal as AbortSignal).reason ??
                  new DOMException("The operation was aborted.", "TimeoutError"),
              );
            });
          });
        }),
      );

      const { GET } = await import("./route");
      const req = new Request("http://localhost:3000/api/portfolio/summary");

      const resPromise = GET(req, {
        params: Promise.resolve({ path: ["portfolio", "summary"] }),
      });
      await vi.advanceTimersByTimeAsync(30_000);
      const res = await resPromise;

      expect(res.status).toBe(504);
      expect(res.headers.get("Content-Type")).toContain("application/json");
      const body = await res.json();
      expect(body.detail).toMatch(/timed out/i);
    } finally {
      vi.useRealTimers();
    }
  });

  it("returns a JSON 502, not an uncaught exception, when the response body stream fails mid-read", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    // Regression: fetch() resolving only means headers arrived. If the
    // upstream connection drops while the body is still streaming (e.g. the
    // API process crashes/restarts mid-response), reading the body rejects
    // — historically after the try/catch that guards fetch() itself, so it
    // escaped uncaught and Next.js rendered its own HTML 500.
    const upstream = new Response("ok", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    vi.spyOn(upstream, "text").mockRejectedValue(new TypeError("terminated"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(upstream));

    const { GET } = await import("./route");
    const req = new Request("http://localhost:3000/api/portfolio/summary");
    const res = await GET(req, {
      params: Promise.resolve({ path: ["portfolio", "summary"] }),
    });

    expect(res.status).toBe(502);
    expect(res.headers.get("Content-Type")).toContain("application/json");
    const body = await res.json();
    expect(body.detail).toMatch(/not reachable/i);
    expect(body.detail).not.toMatch(/127\.0\.0\.1|localhost|upstream\.test|Bearer/i);
  });

  it("leaves a successful response untouched", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response('{"ok":true}', {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { GET } = await import("./route");
    const req = new Request("http://localhost:3000/api/portfolio/summary");
    const res = await GET(req, {
      params: Promise.resolve({ path: ["portfolio", "summary"] }),
    });

    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("application/json");
    expect(await res.text()).toBe('{"ok":true}');
  });

  // M5 Task 5.3 — the two-name response-header allowlist. A CSV download keeps
  // its Content-Disposition filename, and nothing else about the upstream
  // server leaks to the browser.

  it("forwards Content-Disposition so a download keeps its filename", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("a,b\n1,2\n", {
          status: 200,
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="pnl-ledger-2026-09-11.csv"',
          },
        }),
      ),
    );

    const { GET } = await import("./route");
    const res = await GET(req("/api/pnl/ledger.csv"), ctx(["pnl", "ledger.csv"]));

    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("text/csv");
    expect(res.headers.get("Content-Disposition")).toContain("pnl-ledger-2026-09-11.csv");
  });

  it("does not forward headers outside the allowlist", async () => {
    process.env.API_TOKEN = "tok";
    process.env.API_URL = "http://upstream.test";

    // The allowlist is the point: a regression to a passthrough would pass
    // every other test in this file, so this is the one that stops it.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("a,b\n1,2\n", {
          status: 200,
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            Server: "uvicorn",
            "X-Powered-By": "something",
          },
        }),
      ),
    );

    const { GET } = await import("./route");
    const res = await GET(req("/api/pnl/ledger.csv"), ctx(["pnl", "ledger.csv"]));

    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("text/csv");
    expect(res.headers.get("Server")).toBeNull();
    expect(res.headers.get("X-Powered-By")).toBeNull();
  });
});