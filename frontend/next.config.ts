import type { NextConfig } from "next";

// Where the browser reaches the backend (src/lib/config.ts): its REST API, and its voice socket on
// the same host. Both are fixed at build time, like the client code that uses them.
const api = new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");
const voiceSocket = `${api.protocol === "https:" ? "wss:" : "ws:"}//${api.host}`;
const secure = api.protocol === "https:";

// Without nonces (node_modules/next/dist/docs/01-app/02-guides/content-security-policy.md): a
// nonce would also stop an injected inline script, but it needs every page rendered per request,
// and nothing here renders HTML from data. What this policy does: scripts only from this origin,
// data sent only to this origin and the API, no plugins, no framing, no foreign form targets.
// `unsafe-eval` only in development, where React uses it for error stacks.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data:",
  "font-src 'self'",
  `connect-src 'self' ${api.origin} ${voiceSocket}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  ...(secure ? ["upgrade-insecure-requests"] : []),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // For browsers older than CSP's frame-ancestors.
  { key: "X-Frame-Options", value: "DENY" },
  // The microphone is the product; nothing else is asked for.
  {
    key: "Permissions-Policy",
    value: "microphone=(self), camera=(), geolocation=(), browsing-topics=()",
  },
  // Only where the deployment serves TLS; a browser ignores it over plain HTTP anyway.
  ...(secure
    ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }]
    : []),
];

const nextConfig: NextConfig = {
  // A self-contained server for the container image (infra/docker/frontend.Dockerfile).
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
