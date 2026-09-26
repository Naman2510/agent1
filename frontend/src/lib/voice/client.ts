import { getAccessToken, onAccessTokenChange, refreshAccessToken } from "@/lib/auth/tokens";
import { voiceSocketUrl } from "@/lib/config";
import { PlaybackQueue } from "@/lib/voice/playback";
import {
  decodeAudio,
  encodeAudio,
  micTurnId,
  type CitationFrame,
  type ServerFrame,
  type TurnState,
} from "@/lib/voice/protocol";

export interface TurnDetails {
  turnId: number;
  tools: { tool_name: string; ok: boolean }[];
  citations: CitationFrame[];
  latencyMs: Record<string, number> | null;
}

export interface VoiceSnapshot {
  connection: "idle" | "connecting" | "open" | "closed";
  closeReason: string | null;
  state: TurnState;
  turnId: number;
  mic: "off" | "on" | "blocked";
  muted: boolean;
  level: number;
  heard: string;
  reply: string;
  replyTurn: number | null;
  interrupted: boolean;
  details: TurnDetails | null;
  error: { code: string; message: string } | null;
  /** Bumped whenever the server finishes a turn, so the page can reload the stored transcript. */
  finishedTurns: number;
}

const INITIAL: VoiceSnapshot = {
  connection: "idle",
  closeReason: null,
  state: "idle",
  turnId: 0,
  mic: "off",
  muted: false,
  level: 0,
  heard: "",
  reply: "",
  replyTurn: null,
  interrupted: false,
  details: null,
  error: null,
  finishedTurns: 0,
};

const ACK_INTERVAL_MS = 200;
// Past about two seconds of unsent audio the connection is not keeping up, and old speech is
// worth less than a live stream.
const MAX_BUFFERED_BYTES = 64_000;

export class VoiceClient {
  private snapshot: VoiceSnapshot = INITIAL;
  private readonly listeners = new Set<() => void>();
  private socket: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private playback: PlaybackQueue | null = null;
  private stream: MediaStream | null = null;
  private capture: AudioWorkletNode | null = null;
  private ackTimer: ReturnType<typeof setInterval> | null = null;
  private lastAck: { turnId: number; playedMs: number } | null = null;
  private micSeq = 0;
  private stopReauth: (() => void) | null = null;

  constructor(private readonly sessionId: string) {}

  // --- store (useSyncExternalStore) ---------------------------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): VoiceSnapshot => this.snapshot;

  private update(patch: Partial<VoiceSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of this.listeners) listener();
  }

  // --- lifecycle ------------------------------------------------------------------------------

  /** Must run inside a click handler: browsers only start audio from a user gesture. */
  async start(): Promise<void> {
    if (this.snapshot.connection === "connecting" || this.snapshot.connection === "open") return;
    this.update({ connection: "connecting", closeReason: null, error: null });

    this.ctx ??= new AudioContext({ latencyHint: "interactive" });
    await this.ctx.resume();

    const token = getAccessToken() ?? (await refreshAccessToken().catch(() => null));
    if (token === null) {
      this.update({ connection: "closed", closeReason: "You are signed out." });
      return;
    }

    const socket = new WebSocket(voiceSocketUrl(this.sessionId), ["bearer", token]);
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    // A reconnect replaces the socket; the old one's late events must not touch the new one.
    socket.onmessage = (event) => {
      if (this.socket === socket) this.onMessage(event);
    };
    socket.onclose = (event) => {
      if (this.socket === socket) this.onClose(event);
    };
    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.update({ connection: "open" });
      void this.startMic();
    };

    // The socket lives only as long as its newest token, so every refresh is passed along.
    this.stopReauth = onAccessTokenChange((fresh) => {
      if (fresh !== null) this.sendControl({ type: "session.reauth", access_token: fresh });
    });
  }

  close(): void {
    if (this.socket === null && this.snapshot.connection === "idle") return;
    this.sendControl({ type: "session.end" });
    this.teardown();
    this.socket?.close(1000, "bye");
    this.socket = null;
    this.update({ connection: "closed", closeReason: null, mic: "off", level: 0 });
  }

  private teardown(): void {
    this.stopReauth?.();
    this.stopReauth = null;
    if (this.ackTimer !== null) clearInterval(this.ackTimer);
    this.ackTimer = null;
    this.capture?.disconnect();
    this.capture = null;
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    this.playback?.close();
    this.playback = null;
    void this.ctx?.close();
    this.ctx = null;
  }

  private onClose(event: CloseEvent): void {
    this.teardown();
    this.socket = null;
    const reason =
      event.code === 1000
        ? null
        : event.reason === "credential expired"
          ? "Your sign-in expired. Reconnect to continue."
          : event.reason || "The voice connection closed.";
    this.update({ connection: "closed", closeReason: reason, mic: "off", level: 0 });
  }

  // --- microphone -----------------------------------------------------------------------------

  private async startMic(): Promise<void> {
    const ctx = this.ctx;
    if (ctx === null) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          // Helps, but cannot fully cancel the mentor's voice from a laptop speaker; headphones
          // are the dependable fix for self-interruption (RISKS.md R-07).
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
    } catch {
      this.update({ mic: "blocked" });
      return;
    }
    await ctx.audioWorklet.addModule("/voice-capture-worklet.js");
    const source = ctx.createMediaStreamSource(this.stream);
    this.capture = new AudioWorkletNode(ctx, "vaani-capture");
    this.capture.port.onmessage = (event: MessageEvent<ArrayBuffer>) => this.onMicFrame(event.data);
    source.connect(this.capture);
    this.update({ mic: "on" });
  }

  private onMicFrame(pcm: ArrayBuffer): void {
    const socket = this.socket;
    if (socket === null || socket.readyState !== WebSocket.OPEN) return;
    const samples = new Int16Array(pcm);
    let energy = 0;
    for (const sample of samples) energy += sample * sample;
    const level = Math.min(1, Math.sqrt(energy / samples.length) / 6000);
    if (Math.abs(level - this.snapshot.level) > 0.05) this.update({ level });

    if (this.snapshot.muted || socket.bufferedAmount > MAX_BUFFERED_BYTES) return;
    const { state, turnId } = this.snapshot;
    socket.send(encodeAudio(micTurnId(state, turnId), this.micSeq++, pcm));
  }

  setMuted(muted: boolean): void {
    this.update({ muted, level: muted ? 0 : this.snapshot.level });
  }

  // --- student actions ------------------------------------------------------------------------

  /** The stop button. Silence first — it is the only part the student perceives — then tell the server. */
  interrupt(): void {
    const { turnId } = this.snapshot;
    this.flushPlayback(turnId);
    this.sendControl({ type: "user.interrupt", turn_id: turnId });
  }

  sendText(text: string): void {
    // A typed question has no stt.final to echo it back, so it is shown from here.
    this.update({ heard: text, reply: "", replyTurn: null, interrupted: false, error: null });
    this.sendControl({ type: "user.text", text });
  }

  private sendControl(message: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(message));
  }

  // --- inbound --------------------------------------------------------------------------------

  private onMessage(event: MessageEvent<ArrayBuffer | string>): void {
    if (typeof event.data !== "string") {
      this.onAudio(event.data);
      return;
    }
    let frame: ServerFrame;
    try {
      frame = JSON.parse(event.data) as ServerFrame;
    } catch {
      return;
    }
    switch (frame.type) {
      case "ready":
        if (this.ctx !== null) this.playback = new PlaybackQueue(this.ctx, frame.tts_sample_rate);
        break;
      case "state": {
        // The server advances turn_id exactly when a turn is over — heard in full, cancelled, or
        // cut off. Its captions give way to the stored transcript; its details stay on show.
        const advanced = frame.turn_id > this.snapshot.turnId;
        this.update({
          state: frame.state,
          turnId: frame.turn_id,
          ...(advanced
            ? {
                finishedTurns: this.snapshot.finishedTurns + 1,
                heard: "",
                reply: "",
                replyTurn: null,
                interrupted: false,
              }
            : {}),
        });
        break;
      }
      case "stt.partial":
        this.update({ heard: frame.text });
        break;
      case "stt.final":
        this.update({
          heard: frame.text,
          reply: "",
          replyTurn: frame.turn_id,
          interrupted: false,
          error: null,
        });
        break;
      case "llm.delta":
        this.update(
          frame.turn_id === this.snapshot.replyTurn
            ? { reply: this.snapshot.reply + frame.text }
            : { reply: frame.text, replyTurn: frame.turn_id, interrupted: false },
        );
        break;
      case "tts.cancel":
        this.flushPlayback(frame.turn_id);
        this.update({ interrupted: true });
        break;
      case "metrics":
        this.update({ details: { ...this.detailsFor(frame.turn_id), latencyMs: frame.latency_ms } });
        break;
      case "agent.activity":
        this.update({ details: { ...this.detailsFor(frame.turn_id), tools: frame.tools } });
        break;
      case "rag.citations":
        this.update({ details: { ...this.detailsFor(frame.turn_id), citations: frame.citations } });
        break;
      case "error":
        this.update({ error: { code: frame.code, message: frame.message } });
        break;
    }
  }

  private detailsFor(turnId: number): TurnDetails {
    const current = this.snapshot.details;
    return current !== null && current.turnId === turnId
      ? current
      : { turnId, tools: [], citations: [], latencyMs: null };
  }

  private onAudio(data: ArrayBuffer): void {
    if (this.playback === null) return;
    const { turnId, pcm } = decodeAudio(data);
    if (this.playback.enqueue(turnId, pcm) && this.ackTimer === null) {
      this.ackTimer = setInterval(() => this.acknowledge(), ACK_INTERVAL_MS);
    }
  }

  // --- playback ACKs --------------------------------------------------------------------------

  /**
   * Report how much of the current turn has been heard. The server keeps the turn open (and
   * interruptible) until these cover all of its audio, so the last one matters as much as the first.
   */
  private acknowledge(): void {
    const playback = this.playback;
    const turnId = playback?.currentTurn ?? null;
    if (playback === null || turnId === null) return;
    const playedMs = playback.playedMs(turnId);
    if (this.lastAck?.turnId !== turnId || this.lastAck.playedMs !== playedMs) {
      this.sendControl({ type: "playback.ack", turn_id: turnId, played_ms: playedMs });
      this.lastAck = { turnId, playedMs };
    }
    if (playedMs >= playback.totalMs(turnId) && this.ackTimer !== null) {
      clearInterval(this.ackTimer);
      this.ackTimer = null;
    }
  }

  private flushPlayback(turnId: number): void {
    if (this.playback === null) return;
    const playedMs = this.playback.flush(turnId);
    this.sendControl({ type: "playback.ack", turn_id: turnId, played_ms: playedMs });
    this.lastAck = { turnId, playedMs };
  }
}
