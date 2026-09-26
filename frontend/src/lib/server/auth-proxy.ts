import { NextResponse } from "next/server";

import type { AccessGrant } from "@/lib/api/types";

// The auth proxy: the only code that ever holds a refresh token. The backend issues it in a JSON
// body; this layer moves it into an httpOnly cookie on the app's own origin, so page script (and
// therefore any injected script) never sees the 30-day credential — only the 15-minute access
// token it has to hold anyway.

export const REFRESH_COOKIE = "vaanios_refresh";

// Mirrors the backend's refresh_token_ttl_seconds default. A cookie that outlives its token just
// earns a 401 on the next refresh, which clears it.
const REFRESH_COOKIE_MAX_AGE = 30 * 24 * 3600;

const MAX_BODY_CHARS = 16_384;

const BACKEND_URL = (
  process.env.VAANIOS_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

const cookieOptions = {
  httpOnly: true,
  sameSite: "strict" as const,
  secure: process.env.NODE_ENV === "production",
  // Sent to the auth proxy and nowhere else — not with every page and asset request.
  path: "/api/auth",
};

/**
 * These endpoints set and spend the refresh cookie, so a cross-site page must not be able to
 * drive them. SameSite=Strict already withholds the cookie; this is the second lock, and it also
 * covers login and register, which have no cookie to withhold yet.
 */
export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (origin === null || host === null) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/**
 * The address to rate-limit by, for the backend. Only the rightmost hop counts: it was added by
 * whatever sits directly in front of this server (a reverse proxy, or Next recording the socket
 * peer). Anything to its left came from the client and proves nothing. docs/SECURITY.md §4 has
 * the deployment requirement this relies on.
 */
export function clientAddress(request: Request): string | null {
  const hops = (request.headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((hop) => hop.trim())
    .filter(Boolean);
  return hops.at(-1) ?? null;
}

export async function callBackend(path: string, body: string, request: Request): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const client = clientAddress(request);
  if (client !== null) headers["X-Forwarded-For"] = client;
  try {
    return await fetch(`${BACKEND_URL}${path}`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { error: { code: "backend_unavailable", message: "VaaniOS is unreachable right now." } },
      { status: 502 },
    );
  }
}

export function rejectCrossSite(): NextResponse {
  return NextResponse.json(
    { error: { code: "permission_denied", message: "Cross-site request refused." } },
    { status: 403 },
  );
}

export async function readJsonBody(request: Request): Promise<string | NextResponse> {
  if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
    return NextResponse.json(
      { error: { code: "unsupported_media_type", message: "Expected JSON." } },
      { status: 415 },
    );
  }
  const body = await request.text();
  if (body.length > MAX_BODY_CHARS) {
    return NextResponse.json(
      { error: { code: "payload_too_large", message: "Request too large." } },
      { status: 413 },
    );
  }
  return body;
}

/** Turn a backend token response into an access grant for the page plus a refresh cookie. */
export async function grantFrom(upstream: Response): Promise<NextResponse> {
  if (!upstream.ok) {
    return relayError(upstream);
  }
  const tokens = (await upstream.json()) as AccessGrant & { refresh_token: string };
  const grant: AccessGrant = { access_token: tokens.access_token, expires_in: tokens.expires_in };
  const response = NextResponse.json(grant, { headers: { "Cache-Control": "no-store" } });
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...cookieOptions,
    maxAge: REFRESH_COOKIE_MAX_AGE,
  });
  return response;
}

export function clearRefreshCookie(response: NextResponse): NextResponse {
  response.cookies.set(REFRESH_COOKIE, "", { ...cookieOptions, maxAge: 0 });
  return response;
}

export async function relayError(upstream: Response): Promise<NextResponse> {
  const body = await upstream.text();
  const headers: Record<string, string> = {
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
  };
  const retryAfter = upstream.headers.get("retry-after");
  if (retryAfter !== null) headers["Retry-After"] = retryAfter;
  return new NextResponse(body, { status: upstream.status, headers });
}
