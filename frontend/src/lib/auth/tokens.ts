import type { AccessGrant } from "@/lib/api/types";

// The access token lives only in memory: short-lived (15 min), and needed by script anyway for
// the Authorization header and the voice socket's subprotocol. The 30-day refresh token never
// reaches script at all — it sits in an httpOnly cookie that only the auth proxy
// (app/api/auth/*) can read.

type Listener = (token: string | null) => void;

// Refresh this long before expiry, so a request never races the token's last second.
const REFRESH_MARGIN_MS = 60_000;

let accessToken: string | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let inflight: Promise<string | null> | null = null;
const listeners = new Set<Listener>();

export function getAccessToken(): string | null {
  return accessToken;
}

export function onAccessTokenChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setAccessGrant(grant: AccessGrant | null): void {
  accessToken = grant?.access_token ?? null;
  if (refreshTimer !== null) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
  if (grant !== null) {
    const delay = Math.max(grant.expires_in * 1000 - REFRESH_MARGIN_MS, 5_000);
    refreshTimer = setTimeout(() => {
      // A failure clears the session via setAccessGrant(null); listeners hear about it.
      void refreshAccessToken().catch(() => undefined);
    }, delay);
  }
  for (const listener of listeners) listener(accessToken);
}

/**
 * Trade the refresh cookie for a new access token. Resolves to null when there is no session.
 *
 * Every tab shares the one cookie, and the backend revokes the whole token family when a rotated
 * token is presented again — so two tabs refreshing at once would sign the student out
 * everywhere. A Web Lock serialises refreshes across tabs; `inflight` collapses concurrent
 * callers within one tab into a single request.
 */
export function refreshAccessToken(): Promise<string | null> {
  if (inflight === null) {
    inflight = withCrossTabLock(async () => {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
      });
      // 204: never signed in. 401: the session ended (expired, revoked, or signed out elsewhere).
      if (response.status === 204 || response.status === 401) {
        setAccessGrant(null);
        return null;
      }
      if (!response.ok) {
        // Rate limited or the backend is down: the session may still be good, so keep it.
        throw new Error(`refresh failed with ${response.status}`);
      }
      const grant = (await response.json()) as AccessGrant;
      setAccessGrant(grant);
      return grant.access_token;
    }).finally(() => {
      inflight = null;
    });
  }
  return inflight;
}

async function withCrossTabLock<T>(task: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && "locks" in navigator && navigator.locks) {
    return navigator.locks.request("vaanios-auth-refresh", task);
  }
  return task();
}
