import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The token store is module state; every test gets fresh copies of it and of its dependants.
async function load() {
  vi.resetModules();
  const tokens = await import("@/lib/auth/tokens");
  const client = await import("@/lib/api/client");
  const endpoints = await import("@/lib/api/endpoints");
  const errors = await import("@/lib/api/errors");
  return { ...tokens, ...client, ...endpoints, ...errors };
}

type Route = (url: string, init: RequestInit | undefined) => Response | Promise<Response>;

function routeFetch(route: Route) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => route(String(input), init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const grant = (token: string) => Response.json({ access_token: token, expires_in: 900 });
const bearerOf = (init: RequestInit | undefined) => new Headers(init?.headers).get("Authorization");

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("refreshAccessToken", () => {
  it("collapses concurrent callers into one request", async () => {
    const { refreshAccessToken } = await load();
    const fetchMock = routeFetch(() => grant("t1"));
    const [a, b] = await Promise.all([refreshAccessToken(), refreshAccessToken()]);
    expect([a, b]).toEqual(["t1", "t1"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("signs out on a 401 and tells listeners", async () => {
    const { refreshAccessToken, getAccessToken, onAccessTokenChange, setAccessGrant } = await load();
    setAccessGrant({ access_token: "old", expires_in: 900 });
    const heard: (string | null)[] = [];
    onAccessTokenChange((token) => heard.push(token));
    routeFetch(() => Response.json({ error: { code: "unauthenticated" } }, { status: 401 }));

    expect(await refreshAccessToken()).toBeNull();
    expect(getAccessToken()).toBeNull();
    expect(heard).toEqual([null]);
  });

  it("keeps the session when the refresh fails for a reason unrelated to it", async () => {
    const { refreshAccessToken, getAccessToken, setAccessGrant } = await load();
    setAccessGrant({ access_token: "still-good", expires_in: 900 });
    routeFetch(() => new Response("upstream down", { status: 502 }));

    await expect(refreshAccessToken()).rejects.toThrow(/502/);
    expect(getAccessToken()).toBe("still-good");
  });

  it("refreshes a minute before the access token expires", async () => {
    const { setAccessGrant, getAccessToken } = await load();
    const fetchMock = routeFetch(() => grant("renewed"));
    setAccessGrant({ access_token: "first", expires_in: 900 });

    await vi.advanceTimersByTimeAsync(839_000);
    expect(fetchMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe("renewed");
  });
});

describe("apiFetch", () => {
  it("retries once with a refreshed token after a 401", async () => {
    const { apiJson, setAccessGrant } = await load();
    setAccessGrant({ access_token: "stale", expires_in: 900 });
    const fetchMock = routeFetch((url, init) => {
      if (url === "/api/auth/refresh") return grant("fresh");
      return bearerOf(init) === "Bearer fresh"
        ? Response.json({ ok: true })
        : Response.json({ error: { code: "unauthenticated" } }, { status: 401 });
    });

    expect(await apiJson("/auth/me")).toEqual({ ok: true });
    const backendCalls = fetchMock.mock.calls.filter(([url]) => String(url) !== "/api/auth/refresh");
    expect(backendCalls.map(([, init]) => bearerOf(init))).toEqual(["Bearer stale", "Bearer fresh"]);
  });

  it("gives up after one retry rather than looping", async () => {
    const { apiJson, setAccessGrant, ApiError } = await load();
    setAccessGrant({ access_token: "stale", expires_in: 900 });
    const fetchMock = routeFetch((url) =>
      url === "/api/auth/refresh"
        ? grant("also-rejected")
        : Response.json({ error: { code: "unauthenticated", message: "no" } }, { status: 401 }),
    );

    const failure = await apiJson("/auth/me").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as InstanceType<typeof ApiError>).status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(3); // request, refresh, one retry
  });

  it("does not call the backend at all without a session", async () => {
    const { apiJson } = await load();
    const fetchMock = routeFetch((url) =>
      url === "/api/auth/refresh" ? new Response(null, { status: 204 }) : Response.json({ ok: true }),
    );
    await expect(apiJson("/auth/me")).rejects.toMatchObject({ status: 401, code: "unauthenticated" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("sendTextTurn", () => {
  function sse(...pieces: string[]): Response {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const piece of pieces) controller.enqueue(new TextEncoder().encode(piece));
        controller.close();
      },
    });
    return new Response(body, { headers: { "content-type": "text/event-stream" } });
  }

  it("reassembles events split across network chunks", async () => {
    const { sendTextTurn, setAccessGrant } = await load();
    setAccessGrant({ access_token: "t", expires_in: 900 });
    routeFetch(() =>
      sse(
        'event: delta\ndata: {"text":"Hel"}\n\nevent: del',
        'ta\ndata: {"text":"lo"}\n\n',
        'event: done\ndata: {"turn_index":0,"stop_reason":"end_turn","interrupted":false,',
        '"language":"en","latency_ms":{},"estimated_cost_usd":0,"token_usage":{}}\n\n',
      ),
    );
    const deltas: string[] = [];
    const summary = await sendTextTurn("s1", "hi", { onDelta: (text) => deltas.push(text) });
    expect(deltas).toEqual(["Hel", "lo"]);
    expect(summary.stop_reason).toBe("end_turn");
  });

  it("turns a terminal error event into an ApiError", async () => {
    const { sendTextTurn, setAccessGrant } = await load();
    setAccessGrant({ access_token: "t", expires_in: 900 });
    routeFetch(() =>
      sse('event: error\ndata: {"code":"spend_cap_exceeded","message":"Monthly budget reached."}\n\n'),
    );
    await expect(sendTextTurn("s1", "hi", { onDelta: () => undefined })).rejects.toMatchObject({
      code: "spend_cap_exceeded",
    });
  });

  it("reports a stream that ends without a verdict", async () => {
    const { sendTextTurn, setAccessGrant } = await load();
    setAccessGrant({ access_token: "t", expires_in: 900 });
    routeFetch(() => sse('event: delta\ndata: {"text":"partial"}\n\n'));
    await expect(sendTextTurn("s1", "hi", { onDelta: () => undefined })).rejects.toMatchObject({
      code: "stream_ended",
    });
  });
});

describe("safeNext", () => {
  it("allows only same-app paths", async () => {
    const { safeNext } = await import("@/lib/auth/AuthProvider");
    expect(safeNext("/sessions/abc")).toBe("/sessions/abc");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext(undefined)).toBe("/");
  });
});
