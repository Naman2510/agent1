import { expect, test } from "@playwright/test";

import { fakeMicrophone, QUESTION_WAV } from "./support/audio";
import { FAKE_REPLY, FAKE_TRANSCRIPT, newStudent, register, startSession } from "./support/stack";
import { INTERRUPTED, startTalking, statusLine, transcript, watchVoiceSocket } from "./support/voice";

// Spoken, through the whole capture path: the audio worklet's resampling, 20 ms frames on the
// socket, and the real Silero VAD deciding where speech starts and stops. Only what the words
// are is faked (the STT), so the transcript text is the fake's, whatever was said.
test.use({ launchOptions: { args: fakeMicrophone(QUESTION_WAV, { loop: false }) } });

test("a spoken question is heard, answered, played out and kept", async ({ page }) => {
  const wire = watchVoiceSocket(page);
  await register(page, newStudent("spoken"));
  await startSession(page, "Start talking");
  await startTalking(page);

  await expect(transcript(page)).toHaveCount(2, { timeout: 45_000 });
  await expect(transcript(page).nth(0)).toContainText(FAKE_TRANSCRIPT);
  await expect(transcript(page).nth(1)).toContainText(FAKE_REPLY);
  await expect(transcript(page).nth(1)).not.toContainText(INTERRUPTED);
  await expect(statusLine(page)).toHaveText("Listening — ask anything");

  // The VAD found the speech in the recording: the turn began because the student spoke.
  expect(wire.states).toEqual(
    expect.arrayContaining(["user_speaking", "thinking", "speaking", "listening"]),
  );
  expect(wire.states.indexOf("user_speaking")).toBeLessThan(wire.states.indexOf("thinking"));
  expect(wire.received).toContain("stt.final");
  expect(wire.received).not.toContain("tts.cancel");
});
