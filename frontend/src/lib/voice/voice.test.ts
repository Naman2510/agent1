import { describe, expect, it } from "vitest";

import { PlaybackQueue, type PlaybackContext } from "@/lib/voice/playback";
import { decodeAudio, encodeAudio, micTurnId } from "@/lib/voice/protocol";

const RATE = 24_000;

/** Enough of an AudioContext for the queue: a settable clock and recorded start/stop calls. */
class FakeContext {
  currentTime = 0;
  outputLatency = 0;
  baseLatency = 0;
  readonly destination = {} as AudioDestinationNode;
  readonly sources: { at: number; stopped: boolean }[] = [];

  createBuffer(_channels: number, length: number, sampleRate: number): AudioBuffer {
    const data = new Float32Array(length);
    return { duration: length / sampleRate, getChannelData: () => data } as unknown as AudioBuffer;
  }

  createBufferSource(): AudioBufferSourceNode {
    const record = { at: -1, stopped: false };
    this.sources.push(record);
    return {
      buffer: null,
      connect: () => undefined,
      disconnect: () => undefined,
      start: (at: number) => {
        record.at = at;
      },
      stop: () => {
        record.stopped = true;
      },
    } as unknown as AudioBufferSourceNode;
  }
}

const frame = (ms: number) => new Int16Array((RATE * ms) / 1000);

function queue() {
  const ctx = new FakeContext();
  return { ctx, playback: new PlaybackQueue(ctx as unknown as PlaybackContext, RATE) };
}

describe("PlaybackQueue", () => {
  it("counts only what has left the speaker, net of output latency", () => {
    const { ctx, playback } = queue();
    for (let i = 0; i < 3; i++) playback.enqueue(5, frame(100)); // starts at 0.06, 0.16, 0.26
    ctx.outputLatency = 0.05;

    ctx.currentTime = 0.21; // heard up to 0.16: exactly the first frame
    expect(playback.playedMs(5)).toBe(100);

    ctx.currentTime = 10;
    expect(playback.playedMs(5)).toBe(300);
    expect(playback.playedMs(5)).toBe(playback.totalMs(5));
  });

  it("does not count a gap in the stream as heard audio", () => {
    const { ctx, playback } = queue();
    playback.enqueue(1, frame(100)); // 0.06 – 0.16
    ctx.currentTime = 1.0;
    playback.enqueue(1, frame(100)); // arrives late: 1.06 – 1.16, not 0.16 – 0.26
    ctx.currentTime = 1.1;
    expect(playback.playedMs(1)).toBe(140);
  });

  it("flush silences the turn, reports what was heard, and fences its stragglers", () => {
    const { ctx, playback } = queue();
    playback.enqueue(2, frame(100));
    playback.enqueue(2, frame(100));
    ctx.currentTime = 0.11;

    expect(playback.flush(2)).toBe(50);
    expect(ctx.sources.every((source) => source.stopped)).toBe(true);
    expect(playback.enqueue(2, frame(100))).toBe(false); // sent before the server stopped
    expect(playback.currentTurn).toBeNull();
    expect(playback.enqueue(3, frame(100))).toBe(true); // the next turn plays normally
    expect(playback.currentTurn).toBe(3);
  });

  it("schedules frames back to back so playback is gap-free", () => {
    const { ctx, playback } = queue();
    playback.enqueue(1, frame(100));
    playback.enqueue(1, frame(100));
    const [first, second] = ctx.sources.map((source) => source.at);
    expect(first).toBeCloseTo(0.06, 9);
    expect(second).toBeCloseTo(0.16, 9); // exactly where the first one ends
  });
});

describe("protocol", () => {
  it("round-trips an audio frame with a big-endian header", () => {
    const pcm = new Int16Array([1, -2, 32767, -32768]);
    const wire = encodeAudio(70_000, 3, pcm.buffer);
    expect(new Uint8Array(wire, 0, 4)).toEqual(new Uint8Array([0, 1, 0x11, 0x70]));
    const decoded = decodeAudio(wire);
    expect(decoded.turnId).toBe(70_000);
    expect(decoded.seq).toBe(3);
    expect(Array.from(decoded.pcm)).toEqual([1, -2, 32767, -32768]);
  });

  it("tags mic audio with the next turn while the mentor is responding", () => {
    expect(micTurnId("thinking", 4)).toBe(5);
    expect(micTurnId("speaking", 4)).toBe(5);
    expect(micTurnId("barged_in", 4)).toBe(5);
    expect(micTurnId("listening", 4)).toBe(4);
    expect(micTurnId("user_speaking", 4)).toBe(4);
    expect(micTurnId("error", 4)).toBe(4);
  });
});
