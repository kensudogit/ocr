/**
 * Universal proxy: forwards /api/* → FastAPI backend (http://127.0.0.1:8000/*)
 *
 * This server-side proxy avoids mixed-content errors on Railway (HTTPS page
 * trying to reach http://127.0.0.1:8000 directly from the browser).
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND =
  process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

async function proxy(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  const { path } = await params;
  const targetPath = path.join("/");
  const targetUrl = `${BACKEND}/${targetPath}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!["host", "connection"].includes(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const init: RequestInit = { method: req.method, headers };

  if (!["GET", "HEAD"].includes(req.method)) {
    // @ts-ignore — duplex required for streaming body in Node.js fetch
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

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const PATCH = proxy;
