import type { NextConfig } from "next";

const apiUrl = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8080").replace(/\/$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // AI-backed generation (script, media ranking) can take longer than the 30s default.
  experimental: { proxyTimeout: 180_000 },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiUrl}/api/v1/:path*` }];
  },
};

export default nextConfig;
