import { expect, type Page } from "@playwright/test";

/** What crossed the voice socket, as the browser saw it. */
export interface VoiceWire {
  /** Server state frames, in order: listening, user_speaking, thinking, speaking, ... */
  states: string[];
  /** Every server control frame's type, in order. */
  received: string[];
  /** The browser's playback acknowledgements. */
  acks: { turn_id: number; played_ms: number }[];
  /** Binary messages: synthesized audio in, microphone frames out. */
  audioIn: number;
  micOut: number;
}

export function watchVoiceSocket(page: Page): VoiceWire {
  const wire: VoiceWire = { states: [], received: [], acks: [], audioIn: 0, micOut: 0 };
  page.on("websocket", (socket) => {
    if (!socket.url().includes("/v1/voice/ws")) return;
    socket.on("framereceived", ({ payload }) => {
      if (typeof payload !== "string") {
        wire.audioIn += 1;
        return;
      }
      const frame = JSON.parse(payload) as { type: string; state?: string };
      wire.received.push(frame.type);
      if (frame.type === "state" && frame.state) wire.states.push(frame.state);
    });
    socket.on("framesent", ({ payload }) => {
      if (typeof payload !== "string") {
        wire.micOut += 1;
        return;
      }
      const frame = JSON.parse(payload) as { type: string; turn_id: number; played_ms: number };
      if (frame.type === "playback.ack") wire.acks.push(frame);
    });
  });
  return wire;
}

/** The voice panel's own status line. */
export const statusLine = (page: Page) => page.locator("p[aria-live=polite]");

/** From a voice session's page: connect, and wait until the mentor is listening. */
export async function startTalking(page: Page): Promise<void> {
  await expect(page.getByText("Ready when you are")).toBeVisible();
  await page.getByRole("button", { name: "Start talking" }).click();
  await expect(statusLine(page)).toHaveText("Listening — ask anything");
  await expect(page.getByText("Microphone on")).toBeVisible();
}

export const transcript = (page: Page) =>
  page.getByRole("list", { name: "Transcript" }).getByRole("listitem");

/** An answer the student cut off, in the transcript. */
export const INTERRUPTED = /you interrupted here|Interrupted before any of it played/;
