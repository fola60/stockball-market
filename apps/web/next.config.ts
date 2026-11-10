import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async redirects() {
    return [{ source: "/blind-market", destination: "/daily-games", permanent: true }];
  },
};

export default nextConfig;
