import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // /api/* is handled by app/api/[...path]/route.ts (server-side proxy to FastAPI)
};

export default nextConfig;
