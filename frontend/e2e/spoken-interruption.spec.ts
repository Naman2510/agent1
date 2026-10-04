import { expect, test } from "@playwright/test";

import { fakeMicrophone, INTERRUPTION_WAV } from "./support/audio";
import { FAKE_REPLY, FAKE_TRANSCRIPT, newStudent, register, startSession } from "./support/stack";
import { INTERRUPTED, startTalking, statusLine, transcript, watchVoiceSocket } from "./support/voice";

// The recording asks a question, then asks again while the answer is playing (support/audio.ts).
test.use({ launchOptions: { args: fakeMicrophone(INTERRUPTION_WAV, { loop: false }) } });

test("speaking over the answer interrupts it, and becomes the next question", async ({ page }) => {
  const wire = watchVoiceSocket(page);
  await register(page, newStudent("bargein"));
  await startSession(page, "Start talking");
  await startTalking(page);

  await expect(transcript(page)).toHaveCount(4, { timeout: 60_000 });
  await expect(transcript(page).nth(1)).toContainText(INTERRUPTED);
  await expect(transcript(page).nth(2)).toContainText(FAKE_TRANSCRIPT);
  await expect(transcript(page).nth(3)).toContainText(FAKE_REPLY);
  await expect(transcript(page).nth(3)).not.toContainText(INTERRUPTED);
  await expect(statusLine(page)).toHaveText("Listening — ask anything");

  expect(wire.received).toContain("tts.cancel");
  expect(wire.states).toContain("barged_in");
});
