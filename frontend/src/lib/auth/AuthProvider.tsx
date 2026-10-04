"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getMe } from "@/lib/api/endpoints";
import { ApiError, toApiError } from "@/lib/api/errors";
import type { AccessGrant, Me } from "@/lib/api/types";
import { onAccessTokenChange, refreshAccessToken, setAccessGrant } from "@/lib/auth/tokens";

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "unavailable" }
  | { status: "authenticated"; me: Me };

export interface RegisterInput {
  email: string;
  password: string;
  display_name: string;
  semester?: number | null;
}

interface AuthContextValue {
  state: AuthState;
  login: (email: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  logout: () => Promise<void>;
  retry: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function requestGrant(path: string, payload: unknown): Promise<AccessGrant> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    credentials: "same-origin",
  });
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as AccessGrant;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  const loadMe = useCallback(async () => {
    const me = await getMe();
    setState({ status: "authenticated", me });
  }, []);

  useEffect(() => {
    let active = true;
    const unsubscribe = onAccessTokenChange((token) => {
      if (token === null && active) setState({ status: "anonymous" });
    });
    // A page load starts with no access token: the refresh cookie, if any, is the session.
    refreshAccessToken()
      .then(async (token) => {
        if (!active) return;
        if (token === null) setState({ status: "anonymous" });
        else await loadMe();
      })
      .catch((error: unknown) => {
        if (!active) return;
        // Rate limited or unreachable says nothing about whether the student is signed in, so
        // it must not bounce them to the login page.
        const signedOut = error instanceof ApiError && error.status === 401;
        setState({ status: signedOut ? "anonymous" : "unavailable" });
      });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [loadMe, attempt]);

  const login = useCallback(
    async (email: string, password: string) => {
      setAccessGrant(await requestGrant("/api/auth/login", { email, password }));
      await loadMe();
    },
    [loadMe],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      setAccessGrant(await requestGrant("/api/auth/register", input));
      await loadMe();
    },
    [loadMe],
  );

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      setAccessGrant(null);
    }
  }, []);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo(
    () => ({ state, login, register, logout, retry }),
    [state, login, register, logout, retry],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

/** Only same-app paths: `?next=https://evil.example` must not turn login into a redirector. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  return next;
}
