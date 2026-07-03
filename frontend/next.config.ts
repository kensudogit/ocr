import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "standalone",
  // Multiple lockfiles exist in C:\devlop causing Next.js to pick the wrong
  // workspace root. Pinning it here ensures API routes resolve correctly in
  // the standalone build.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
