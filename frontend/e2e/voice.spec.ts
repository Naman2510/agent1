import { expect, test } from "@playwright/test";

import { FAKE_REPLY, newStudent, register, startSession } from "./support/stack";
import { INTERRUPTED, startTalking, statusLine, transcript, watchVoiceSocket } from "./support/voice";

const QUESTION = "Kirchhoff ka current law bhi samjhao";

test("a question typed into a voice session is answered aloud, played out and kept", async ({
  page,
}) => {
  const wire = watchVoiceSocket(page);
  await register(page, newStudent("voice"));
  await startSession(page, "Start talking");
  await startTalking(page);

  await page.getByLabel("Or type your question").fill(QUESTION);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(`Mentor: ${FAKE_REPLY}`)).toBeVisible();
  await expect(statusLine(page)).toHaveText("Listening — ask anything");

  await expect(transcript(page)).toHaveCount(2);
  await expect(transcript(page).nth(0)).toContainText(QUESTION);
  await expect(transcript(page).nth(1)).toContainText(FAKE_REPLY);
  await expect(transcript(page).nth(1)).not.toContainText(INTERRUPTED);

  // The turn ended because the browser reported the audio played, not on a timer: the server
  // stays in `speaking` until acknowledgements cover everything it sent (~2.2 s of it here).
  expect(wire.audioIn).toBeGreaterThan(0);
  expect(wire.acks.at(-1)?.played_ms).toBeGreaterThan(2_000);
  expect(wire.states.slice(-2)).toEqual(["speaking", "listening"]);
  expect(wire.micOut).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Hang up" }).click();
  await expect(page.getByText("Voice is off")).toBeVisible();
});

test("Stop cuts the answer off, and the transcript keeps only what was heard", async ({
  page,
}) => {
  const wire = watchVoiceSocket(page);
  await register(page, newStudent("stop"));
  await startSession(page, "Start talking");
  await startTalking(page);

  await page.getByLabel("Or type your question").fill(QUESTION);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(statusLine(page)).toHaveText("Speaking");
  await page.getByRole("button", { name: "Stop" }).click();

  await expect(statusLine(page)).toHaveText("Listening — ask anything");
  await expect(transcript(page)).toHaveCount(2);
  const reply = transcript(page).nth(1);
  await expect(reply).toContainText(INTERRUPTED);
  // What is stored is the part that played: a true prefix of the answer, never all of it.
  const heard = (await reply.locator("p").first().innerText()).trim();
  expect(heard).not.toBe(FAKE_REPLY);
  expect(heard === "Interrupted before any of it played." || FAKE_REPLY.startsWith(heard)).toBe(
    true,
  );
  expect(wire.received).toContain("tts.cancel");
});
