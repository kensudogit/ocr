/**
 * Universal proxy: /api/* → FastAPI backend (http://127.0.0.1:8000/*)
 *
 * NOTE: This version avoids using `params` entirely.
 * Next.js 16 changed how catch-all route params work; using
 * `req.nextUrl.pathname` is more reliable across versions.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

async function proxy(req: NextRequest): Promise<NextResponse> {
  // Derive the backend path directly from the request URL.
  // /api/health          → /health
  // /api/documents/      → /documents/
  // /api/upload/?foo=bar → /upload/?foo=bar
  const pathname = req.nextUrl.pathname;
  const backendPath = pathname.replace(/^\/api/, "") || "/";
  const targetUrl = `${BACKEND}${backendPath}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!["host", "connection"].includes(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const init: RequestInit = { method: req.method, headers };
  if (!["GET", "HEAD"].includes(req.method)) {
    // duplex: "half" is required by Node.js fetch for streaming request bodies
    // (e.g. multipart file uploads).
    // @ts-ignore — not yet in TS types but required at runtime
    init.duplex = "half";
    init.body = req.body;
  }

  try {
    const res = await fetch(targetUrl, init);
    const resHeaders = new Headers();
    res.headers.forEach((value, key) => {
      if (!["transfer-encoding", "connection"].includes(key.toLowerCase())) {
        resHeaders.set(key, value);
      }
    });
    return new NextResponse(res.body, {
      status: res.status,
      headers: resHeaders,
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Proxy error: ${String(err)}` },
      { status: 502 }
    );
  }
}

// Explicit named exports (more reliable than `export const GET = proxy`
// across Next.js versions with Turbopack).
export async function GET(req: NextRequest) {
  return proxy(req);
}
export async function POST(req: NextRequest) {
  return proxy(req);
}
export async function PUT(req: NextRequest) {
  return proxy(req);
}
export async function DELETE(req: NextRequest) {
  return proxy(req);
}
export async function PATCH(req: NextRequest) {
  return proxy(req);
}
