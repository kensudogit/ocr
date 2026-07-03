import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "standalone",
  // /api/* is handled by app/api/[...path]/route.ts (server-side proxy to FastAPI)

  // Next.js 16 detects multiple lockfiles and may pick C:\devlop as the workspace
  // root instead of this directory. That causes the standalone build to nest route
  // files under ocr/frontend/.next/... so server.js can't resolve dynamic routes
  // (static pre-rendered pages work; dynamic API routes return "Not Found").
  // Fix: pin the workspace root to this directory.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
