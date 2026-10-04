// Gap-free playback of the mentor's audio, and the honest answer to "how much has been heard?".
//
// That answer is what the server stores as the mentor's side of the conversation when the student
// interrupts (ARCHITECTURE §5.3), so it must come from the audio clock — not from bytes received,
// and never more than has actually left the speaker. The Phase 3 test page reported the
// AudioContext's absolute clock instead, which claims a whole turn was heard the moment it arrived.

export type PlaybackContext = Pick<
  BaseAudioContext,
  "currentTime" | "createBuffer" | "createBufferSource" | "destination"
> & { readonly outputLatency?: number; readonly baseLatency?: number };

// A small cushion so a frame arriving a little late does not click, without delaying the first
// word noticeably.
const JITTER_SECONDS = 0.06;

interface Scheduled {
  turnId: number;
  startAt: number;
  duration: number;
  source: AudioBufferSourceNode;
}

export class PlaybackQueue {
  private scheduled: Scheduled[] = [];
  private playhead = 0;
  private flushedThrough = -1;

  constructor(
    private readonly ctx: PlaybackContext,
    private readonly sampleRate: number,
  ) {}

  /** Schedule a frame of a turn's audio right after whatever is already queued. */
  enqueue(turnId: number, pcm: Int16Array): boolean {
    if (turnId <= this.flushedThrough || pcm.length === 0) return false;
    this.forgetFinishedBefore(turnId);

    const buffer = this.ctx.createBuffer(1, pcm.length, this.sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);
    const startAt = Math.max(this.ctx.currentTime + JITTER_SECONDS, this.playhead);
    source.start(startAt);
    this.playhead = startAt + buffer.duration;
    this.scheduled.push({ turnId, startAt, duration: buffer.duration, source });
    return true;
  }

  /** The newest turn with audio — the one playback ACKs report on. */
  get currentTurn(): number | null {
    let newest: number | null = null;
    for (const item of this.scheduled) if (newest === null || item.turnId > newest) newest = item.turnId;
    return newest;
  }

  /** Milliseconds of a turn's audio that have left the speaker, rounded down. */
  playedMs(turnId: number): number {
    // What the listener hears lags the context's clock by the output path's latency.
    const heard = this.ctx.currentTime - (this.ctx.outputLatency ?? 0) - (this.ctx.baseLatency ?? 0);
    let seconds = 0;
    for (const item of this.scheduled) {
      if (item.turnId === turnId) seconds += Math.min(Math.max(heard - item.startAt, 0), item.duration);
    }
    // Rounded down so nothing is over-claimed; the nanosecond absorbs float error at a boundary,
    // which would otherwise report a fully played 100 ms frame as 99.
    return Math.floor(seconds * 1000 + 1e-6);
  }

  totalMs(turnId: number): number {
    let seconds = 0;
    for (const item of this.scheduled) if (item.turnId === turnId) seconds += item.duration;
    return Math.floor(seconds * 1000 + 1e-6);
  }

  /**
   * Silence a turn immediately (barge-in or the stop button). Returns how much of it was heard.
   * Frames for it that arrive afterwards are dropped: they were sent before the server stopped.
   */
  flush(turnId: number): number {
    const heard = this.playedMs(turnId);
    for (const item of this.scheduled) {
      if (item.turnId <= turnId) stopQuietly(item.source);
    }
    this.scheduled = this.scheduled.filter((item) => item.turnId > turnId);
    this.flushedThrough = Math.max(this.flushedThrough, turnId);
    this.playhead = this.scheduled.reduce((end, item) => Math.max(end, item.startAt + item.duration), 0);
    return heard;
  }

  close(): void {
    for (const item of this.scheduled) stopQuietly(item.source);
    this.scheduled = [];
    this.playhead = 0;
  }

  private forgetFinishedBefore(turnId: number): void {
    const now = this.ctx.currentTime;
    this.scheduled = this.scheduled.filter(
      (item) => item.turnId >= turnId || item.startAt + item.duration > now,
    );
  }
}

function stopQuietly(source: AudioBufferSourceNode): void {
  try {
    source.stop();
  } catch {
    // Already stopped.
  }
  source.disconnect();
}
