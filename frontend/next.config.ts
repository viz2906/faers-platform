import type { NextConfig } from "next";

const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/api\/v1$/, "") ||
  "http://faers-prod-alb-470910505.us-east-1.elb.amazonaws.com";

const nextConfig: NextConfig = {
  // Required for multi-stage Docker builds: produces a self-contained
  // server bundle in .next/standalone that needs no node_modules at runtime.
  output: "standalone",

  // Rewrites allow the Next.js server to proxy /api/v1/* to the FastAPI backend.
  // This means: even if NEXT_PUBLIC_API_URL is wrong at build time,
  // server-side fetches still reach the real backend.
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${API_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
