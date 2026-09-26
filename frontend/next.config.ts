import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A self-contained server for the container image (infra/docker/frontend.Dockerfile).
  output: "standalone",
};

export default nextConfig;
