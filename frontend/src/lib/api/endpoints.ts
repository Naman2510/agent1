import { apiFetch, apiJson } from "@/lib/api/client";
import { ApiError, toApiError } from "@/lib/api/errors";
import type {
  AdminDashboard,
  Me,
  Message,
  PaginatedSessions,
  Session,
  TurnSummary,
} from "@/lib/api/types";

export const getMe = () => apiJson<Me>("/auth/me");

export const listSessions = (limit = 20, offset = 0) =>
  apiJson<PaginatedSessions>(`/sessions?limit=${limit}&offset=${offset}`);

export const getSession = (id: string) => apiJson<Session>(`/sessions/${encodeURIComponent(id)}`);

export const createSession = (transport: "websocket" | "text" = "websocket") =>
  apiJson<Session>("/sessions", { method: "POST", body: JSON.stringify({ transport }) });

export const endSession = (id: string) =>
  apiJson<Session>(`/sessions/${encodeURIComponent(id)}/end`, { method: "POST" });

export const listMessages = (id: string) =>
  apiJson<Message[]>(`/sessions/${encodeURIComponent(id)}/messages`);

export const getAdminDashboard = () => apiJson<AdminDashboard>("/admin/health");

export interface TextTurnHandlers {
  onDelta: (text: string) => void;
  signal?: AbortSignal;
}

/**
 * The typed turn: the backend streams it as server-sent events (`delta`, then `done` or `error`).
 * Read with fetch rather than EventSource, which can neither POST nor send a bearer token.
 */
export async function sendTextTurn(
  sessionId: string,
  text: string,
  { onDelta, signal }: TextTurnHandlers,
): Promise<TurnSummary> {
  const response = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ text }),
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok || response.body === null) {
    throw await toApiError(response);
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const event = parseEvent(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (event === null) continue;
      if (event.name === "delta") {
        onDelta(String((event.data as { text?: unknown }).text ?? ""));
      } else if (event.name === "done") {
        return event.data as TurnSummary;
      } else if (event.name === "error") {
        const { code, message } = event.data as { code?: string; message?: string };
        throw new ApiError(200, code ?? "turn_failed", message ?? "The turn could not be completed.");
      }
    }
  }
  throw new ApiError(0, "stream_ended", "The answer stopped before it finished.");
}

function parseEvent(block: string): { name: string; data: unknown } | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  try {
    return { name, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}
