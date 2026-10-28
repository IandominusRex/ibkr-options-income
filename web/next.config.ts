import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Old URLs keep working (DESIGN.md Brief: stable URLs). Temporary (307) while the
  // overhaul is in flight so no browser caches a destination that may still move.
  async redirects() {
    return [
      { source: "/options", destination: "/trades", permanent: false },
      { source: "/options/:approvalId", destination: "/trades/:approvalId", permanent: false },
      { source: "/pnl", destination: "/activity", permanent: false },
      { source: "/ledger", destination: "/activity?view=ledger", permanent: false },
      { source: "/universe", destination: "/research/universe", permanent: false },
    ];
  },
};

export default nextConfig;
