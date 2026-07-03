/**
 * Dedicated /api/health endpoint.
 *
 * This is a non-catch-all route so it resolves even if the [...path] catch-all
 * has a routing issue.  It proxies to the FastAPI /health endpoint and returns
 * a diagnostic envelope so we can tell whether:
 *   - The Next.js API route layer is working  (proxy:"ok" key is present)
 *   - The FastAPI backend is reachable        (status:"ok")
 *   - Which import errors the backend has     (import_errors:[])
 */

import { NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    const data = await res.json();
    return NextResponse.json({ ...data, proxy: "ok" });
  } catch (err) {
    // Backend unreachable but the Next.js API layer IS working.
    return NextResponse.json(
      {
        status: "backend_unreachable",
        error: String(err),
        proxy: "ok",
        hint: "uvicorn may still be starting — retry in a few seconds",
      },
      { status: 503 }
    );
  }
}
