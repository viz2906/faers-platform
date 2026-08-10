import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Required for multi-stage Docker builds: produces a self-contained
  // server bundle in .next/standalone that needs no node_modules at runtime.
  output: "standalone",
};

export default nextConfig;
