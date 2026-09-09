// Server-side proxy. The browser never holds a credential.
// API_TOKEN has no NEXT_PUBLIC_ prefix, so Next.js cannot inline it.
// See Web plan/P2-design.md §8.

import { NextResponse } from "next/server";

const UPSTREAM = process.env.API_URL ?? "http://127.0.0.1:8787";
const ALLOWED_METHODS = ["GET", "POST", "DELETE"] as const;

async function proxy(
  method: string,
  req: Request,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const token = process.env.API_TOKEN;
  if (!token) {
    return NextResponse.json(
      { detail: "API_TOKEN is not set — the proxy refuses to forward unauthenticated." },
      { status: 500 },
    );
  }

  if (!ALLOWED_METHODS.includes(method as (typeof ALLOWED_METHODS)[number])) {
    return NextResponse.json({ detail: "Method not allowed" }, { status: 405 });
  }

  const { path } = await ctx.params;
  const qs = new URL(req.url).search;
  const target = `${UPSTREAM}/${path.join("/")}${qs}`;

  const init: RequestInit = {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": req.headers.get("Content-Type") ?? "application/json",
    },
  };

  if (method === "POST") {
    init.body = await req.text();
  }

  // Never log the request body — command payloads are not secret, but the habit is.
  const upstream = await fetch(target, init);
  const body = await upstream.text();
  const headers = new Headers();
  const contentType = upstream.headers.get("Content-Type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  // 204/304 and empty bodies must pass a null body through: constructing a
  // Response with a body (even "") at these statuses throws, which would turn
  // a successful live-mode confirm (204) or watchlist remove into a 500.
  if (upstream.status === 204 || upstream.status === 304 || body.length === 0) {
    return new Response(null, { status: upstream.status, headers });
  }
  return new Response(body, { status: upstream.status, headers });
}

export async function GET(
  req: Request,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxy("GET", req, ctx);
}

export async function POST(
  req: Request,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxy("POST", req, ctx);
}

export async function DELETE(
  req: Request,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxy("DELETE", req, ctx);
}

export async function PUT(): Promise<Response> {
  return NextResponse.json({ detail: "Method not allowed" }, { status: 405 });
}

export async function PATCH(): Promise<Response> {
  return NextResponse.json({ detail: "Method not allowed" }, { status: 405 });
}

export async function HEAD(): Promise<Response> {
  return NextResponse.json({ detail: "Method not allowed" }, { status: 405 });
}