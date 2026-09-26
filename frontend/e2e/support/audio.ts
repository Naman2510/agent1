import fs from "node:fs";
import path from "node:path";

/**
 * What the fake microphone plays. Chromium reads a WAV file in place of a capture device
 * (--use-file-for-fake-audio-capture) and plays it in real time from the moment the page opens
 * the microphone, so each recording starts with enough quiet to cover connecting.
 */

/** The committed recording: 16 kHz mono PCM, 0.5 s quiet, 2.65 s of speech, 0.8 s quiet. */
const FIXTURE = path.resolve(
  __dirname,
  "../../../datasets/v1/voice/fixtures/espeak-en-kvl-question.wav",
);
const OUT = path.resolve(__dirname, "../.generated");

export const SILENCE_WAV = path.join(OUT, "silence.wav");
export const QUESTION_WAV = path.join(OUT, "question.wav");
export const INTERRUPTION_WAV = path.join(OUT, "interruption.wav");

/** Chromium flags for a microphone that plays `wav`: once, or on a loop. */
export function fakeMicrophone(wav: string, { loop }: { loop: boolean }): string[] {
  return [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${wav}${loop ? "" : "%noloop"}`,
  ];
}

interface Pcm16 {
  sampleRate: number;
  samples: Buffer;
}

function readWav(file: string): Pcm16 {
  const data = fs.readFileSync(file);
  if (data.toString("ascii", 0, 4) !== "RIFF" || data.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error(`${file} is not a WAV file`);
  }
  let sampleRate = 0;
  let offset = 12;
  while (offset + 8 <= data.length) {
    const id = data.toString("ascii", offset, offset + 4);
    const size = data.readUInt32LE(offset + 4);
    const body = offset + 8;
    if (id === "fmt ") {
      const format = data.readUInt16LE(body);
      const channels = data.readUInt16LE(body + 2);
      const bits = data.readUInt16LE(body + 14);
      if (format !== 1 || channels !== 1 || bits !== 16) {
        throw new Error(`${file}: expected 16-bit mono PCM`);
      }
      sampleRate = data.readUInt32LE(body + 4);
    } else if (id === "data") {
      if (!sampleRate) throw new Error(`${file}: data before fmt`);
      return { sampleRate, samples: data.subarray(body, body + size) };
    }
    offset = body + size + (size % 2);
  }
  throw new Error(`${file}: no data chunk`);
}

function writeWav(file: string, { sampleRate, samples }: Pcm16): void {
  const header = Buffer.alloc(44);
  header.write("RIFF", 0, "ascii");
  header.writeUInt32LE(36 + samples.length, 4);
  header.write("WAVE", 8, "ascii");
  header.write("fmt ", 12, "ascii");
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36, "ascii");
  header.writeUInt32LE(samples.length, 40);
  fs.writeFileSync(file, Buffer.concat([header, samples]));
}

export function writeMicrophoneRecordings(): void {
  const { sampleRate, samples: question } = readWav(FIXTURE);
  const quiet = (seconds: number) => Buffer.alloc(Math.round(seconds * sampleRate) * 2);
  fs.mkdirSync(OUT, { recursive: true });

  writeWav(SILENCE_WAV, { sampleRate, samples: quiet(1) });
  // One question, then quiet for longer than the whole reply takes to play.
  writeWav(QUESTION_WAV, { sampleRate, samples: Buffer.concat([quiet(1.5), question, quiet(8)]) });
  // The question twice. The second starts 1.3 s after the first ends (the fixture's own quiet at
  // either end), by when the ~2.2 s reply to the first is playing: it has to interrupt it.
  writeWav(INTERRUPTION_WAV, {
    sampleRate,
    samples: Buffer.concat([quiet(1.5), question, question, quiet(8)]),
  });
}
