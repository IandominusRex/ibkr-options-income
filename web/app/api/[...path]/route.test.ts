import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Tests for the server-side proxy at app/api/[...path]/route.ts.
// The browser never holds a credential — the proxy injects API_TOKEN server-side.

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
});