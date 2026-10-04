// Where the browser reaches the backend. NEXT_PUBLIC_ values are inlined at build time, so a
// deployment sets this when it builds the image, not when it starts it.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export function voiceSocketUrl(sessionId: string): string {
  const url = new URL(`${API_URL}/v1/voice/ws`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("session_id", sessionId);
  return url.toString();
}
