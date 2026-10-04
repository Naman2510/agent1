import { API_URL } from "@/lib/config";
import { getAccessToken, refreshAccessToken } from "@/lib/auth/tokens";
import { ApiError, toApiError } from "@/lib/api/errors";

/**
 * An authenticated request to the backend. An expired access token costs one refresh and one
 * retry, never a loop: a second 401 means the session really is gone.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let token = getAccessToken() ?? (await refreshAccessToken());
  if (token === null) {
    throw new ApiError(401, "unauthenticated", "You are signed out.");
  }

  const send = (bearer: string) => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${bearer}`);
    if (init.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(`${API_URL}/v1${path}`, { ...init, headers });
  };

  let response = await send(token);
  if (response.status === 401) {
    token = await refreshAccessToken();
    if (token === null) {
      throw new ApiError(401, "unauthenticated", "You are signed out.");
    }
    response = await send(token);
  }
  return response;
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
