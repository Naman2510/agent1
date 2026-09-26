import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

import { POST as login } from "@/app/api/auth/login/route";
import { POST as logout } from "@/app/api/auth/logout/route";
import { POST as refresh } from "@/app/api/auth/refresh/route";
import { REFRESH_COOKIE, clientAddress, isSameOrigin } from "@/lib/server/auth-proxy";

const APP = "http://localhost:3000";

function request(
  path: string,
  { body, cookie, origin = APP, headers = {} }: {
    body?: unknown;
    cookie?: string;
    origin?: string | null;
    headers?: Record<string, string>;
  } = {},
): NextRequest {
  const all: Record<string, string> = { host: "localhost:3000", ...headers };
  if (origin !== null) all.origin = origin;
  if (cookie !== undefined) all.cookie = `${REFRESH_COOKIE}=${cookie}`;
  if (body !== undefined) all["content-type"] = "application/json";
  return new NextRequest(`${APP}${path}`, {
    method: "POST",
    headers: all,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function backend(status: number, body: unknown, headers: Record<string, string> = {}) {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
    Response.json(body, { status, headers: { "content-type": "application/json", ...headers } }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const TOKENS = { access_token: "acc-1", refresh_token: "ref-1", token_type: "bearer", expires_in: 900 };

describe("login", () => {
  it("keeps the refresh token out of the page and in an httpOnly, strict, path-scoped cookie", async () => {
    backend(200, TOKENS);
    const response = await login(request("/api/auth/login", { body: { email: "a@b.co", password: "x" } }));

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual({ access_token: "acc-1", expires_in: 900 });
    expect(JSON.stringify(body)).not.toContain("ref-1");

    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain(`${REFRESH_COOKIE}=ref-1`);
    expect(cookie).toMatch(/HttpOnly/i);
    expect(cookie).toMatch(/SameSite=Strict/i);
    expect(cookie).toMatch(/Path=\/api\/auth/);
  });

  it("refuses a cross-site caller before touching the backend", async () => {
    const fetchMock = backend(200, TOKENS);
    const response = await login(
      request("/api/auth/login", { body: { email: "a@b.co", password: "x" }, origin: "https://evil.example" }),
    );
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a request with no Origin at all", async () => {
    const fetchMock = backend(200, TOKENS);
    const response = await login(request("/api/auth/login", { body: { email: "a@b.co" }, origin: null }));
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("relays the backend's error envelope and status unchanged", async () => {
    backend(401, { error: { code: "invalid_credentials", message: "Invalid email or password." } });
    const response = await login(request("/api/auth/login", { body: { email: "a@b.co", password: "x" } }));
    expect(response.status).toBe(401);
    expect((await response.json()).error.code).toBe("invalid_credentials");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("forwards only the rightmost X-Forwarded-For hop to the backend", async () => {
    const fetchMock = backend(200, TOKENS);
    await login(
      request("/api/auth/login", {
        body: { email: "a@b.co", password: "x" },
        headers: { "x-forwarded-for": "6.6.6.6, 198.51.100.7" },
      }),
    );
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-Forwarded-For"]).toBe("198.51.100.7");
  });

  it("answers an unreachable backend with a JSON 502, not a crash", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("fetch failed");
    }));
    const response = await login(request("/api/auth/login", { body: { email: "a@b.co", password: "x" } }));
    expect(response.status).toBe(502);
    expect((await response.json()).error.code).toBe("backend_unavailable");
  });
});

describe("refresh", () => {
  it("answers a visitor with no cookie with 204, and never calls the backend", async () => {
    const fetchMock = backend(200, TOKENS);
    const response = await refresh(request("/api/auth/refresh"));
    expect(response.status).toBe(204);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rotates the cookie on success", async () => {
    const fetchMock = backend(200, { ...TOKENS, access_token: "acc-2", refresh_token: "ref-2" });
    const response = await refresh(request("/api/auth/refresh", { cookie: "ref-1" }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ access_token: "acc-2", expires_in: 900 });
    expect(response.headers.get("set-cookie")).toContain(`${REFRESH_COOKIE}=ref-2`);
    expect(JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      refresh_token: "ref-1",
    });
  });

  it("clears a dead cookie when the backend rejects it", async () => {
    backend(401, { error: { code: "unauthenticated", message: "Refresh token has been revoked." } });
    const response = await refresh(request("/api/auth/refresh", { cookie: "reused" }));
    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toMatch(new RegExp(`${REFRESH_COOKIE}=;.*Max-Age=0`, "i"));
  });

  it("keeps the cookie when the failure says nothing about the token", async () => {
    backend(429, { error: { code: "rate_limited", message: "Too many requests." } }, { "retry-after": "12" });
    const response = await refresh(request("/api/auth/refresh", { cookie: "ref-1" }));
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("12");
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});

describe("logout", () => {
  it("revokes server-side and clears the cookie", async () => {
    const fetchMock = backend(204, {});
    const response = await logout(request("/api/auth/logout", { cookie: "ref-1" }));
    expect(response.status).toBe(204);
    expect(String(fetchMock.mock.calls[0]?.[0])).toMatch(/\/v1\/auth\/logout$/);
    expect(response.headers.get("set-cookie")).toMatch(/Max-Age=0/i);
  });

  it("still signs the student out when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("fetch failed");
    }));
    const response = await logout(request("/api/auth/logout", { cookie: "ref-1" }));
    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toMatch(/Max-Age=0/i);
  });
});

describe("helpers", () => {
  it("matches the Origin against the host the request arrived on", () => {
    expect(isSameOrigin(new Request(APP, { headers: { origin: APP, host: "localhost:3000" } }))).toBe(true);
    expect(
      isSameOrigin(new Request(APP, { headers: { origin: "http://localhost:3001", host: "localhost:3000" } })),
    ).toBe(false);
    expect(isSameOrigin(new Request(APP, { headers: { origin: "null", host: "localhost:3000" } }))).toBe(false);
  });

  it("takes no address when there is no forwarding header", () => {
    expect(clientAddress(new Request(APP))).toBeNull();
  });
});
