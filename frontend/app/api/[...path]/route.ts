// Server-side proxy to FastAPI. Forwards the Authorization header and streams responses (SSE).
//   /api/health      -> {BACKEND_URL}/health
//   /api/v1/...      -> {BACKEND_URL}/api/v1/...
// Only these two prefixes are forwarded. Everything else returns 404.
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const FORWARD_REQUEST_HEADERS = ["authorization", "content-type", "accept"];
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "cache-control",
  "content-security-policy",
  "x-content-type-options",
];

type Context = { params: Promise<{ path: string[] }> };

function targetPath(segments: string[]): string | null {
  if (segments.length === 1 && segments[0] === "health") return "/health";
  if (segments[0] === "v1" && segments.length >= 2) return `/api/${segments.join("/")}`;
  return null;
}

async function proxy(request: NextRequest, context: Context): Promise<Response> {
  const { path } = await context.params;
  const upstreamPath = targetPath(path);
  if (!upstreamPath) {
    return Response.json({ error: "not_found", message: "Unknown API route" }, { status: 404 });
  }

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const init: RequestInit = { method: request.method, headers, cache: "no-store" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  try {
    const upstream = await fetch(`${BACKEND_URL}${upstreamPath}${request.nextUrl.search}`, init);
    const responseHeaders = new Headers();
    for (const name of FORWARD_RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json(
      { error: "upstream_unavailable", message: "Backend is not reachable" },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
