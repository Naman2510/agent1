// The voice socket's wire format (docs/ARCHITECTURE.md §10). Binary frames carry audio behind an
// 8-byte big-endian header [turn_id:u32][seq:u32]; text frames carry JSON control messages.

export const HEADER_BYTES = 8;

export type TurnState =
  | "idle"
  | "listening"
  | "user_speaking"
  | "thinking"
  | "speaking"
  | "barged_in"
  | "error";

export interface CitationFrame {
  ref: string;
  document_title: string;
  heading_path: string | null;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
}

export type ServerFrame =
  | { type: "ready"; sample_rate: number; frame_ms: number; tts_sample_rate: number }
  | { type: "state"; state: TurnState; turn_id: number }
  | { type: "stt.partial"; text: string; turn_id: number }
  | { type: "stt.final"; text: string; language: string | null; turn_id: number }
  | { type: "llm.delta"; text: string; turn_id: number }
  | { type: "agent.activity"; turn_id: number; tools: { tool_name: string; ok: boolean }[] }
  | { type: "rag.citations"; turn_id: number; citations: CitationFrame[] }
  | { type: "tts.cancel"; turn_id: number }
  | { type: "metrics"; turn_id: number; latency_ms: Record<string, number> }
  | { type: "error"; code: string; message: string };

export function encodeAudio(turnId: number, seq: number, pcm: ArrayBuffer): ArrayBuffer {
  const out = new ArrayBuffer(HEADER_BYTES + pcm.byteLength);
  const view = new DataView(out);
  view.setUint32(0, turnId >>> 0, false);
  view.setUint32(4, seq >>> 0, false);
  new Uint8Array(out, HEADER_BYTES).set(new Uint8Array(pcm));
  return out;
}

export function decodeAudio(data: ArrayBuffer): { turnId: number; seq: number; pcm: Int16Array } {
  const view = new DataView(data);
  // Copied rather than viewed: Int16Array needs 2-byte alignment and the payload starts at 8,
  // which is aligned — but a copy also detaches it from the socket's buffer.
  const pcm = new Int16Array(data.slice(HEADER_BYTES));
  return { turnId: view.getUint32(0, false), seq: view.getUint32(4, false), pcm };
}

/**
 * The turn_id to stamp on microphone audio.
 *
 * The server drops frames tagged below its current turn, and a barge-in advances the turn before
 * the client can hear about it. While the mentor is responding, the next turn is the only tag that
 * is valid both before and after that bump — so the student's interrupting question is never
 * thrown away (§10, "Tagging mic frames").
 */
export function micTurnId(state: TurnState, turnId: number): number {
  return state === "thinking" || state === "speaking" || state === "barged_in" ? turnId + 1 : turnId;
}
