import { expect, test } from "@playwright/test";

import { FAKE_REPLY, newStudent, register, startSession } from "./support/stack";
import { transcript } from "./support/voice";

const QUESTION = "Ohm's law kya hai?";

test("a typed question streams an answer, and both are kept", async ({ page }) => {
  await register(page, newStudent("typed"));
  await startSession(page, "Type instead");
  await expect(page.getByRole("heading", { name: "Typed session" })).toBeVisible();

  await page.getByLabel("Ask your question").fill(QUESTION);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(transcript(page)).toHaveCount(2);
  await expect(transcript(page).nth(0)).toContainText(QUESTION);
  await expect(transcript(page).nth(1)).toContainText(FAKE_REPLY);

  // Stored, not only shown: a fresh load reads them back from the server.
  await page.reload();
  await expect(transcript(page)).toHaveCount(2);

  await page.getByRole("button", { name: "End session" }).click();
  await expect(page.getByLabel("Ask your question")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "End session" })).toHaveCount(0);

  await page.getByRole("link", { name: "← All sessions" }).click();
  const row = page.getByRole("link", { name: /Typed · 1 question/ });
  await expect(row).toBeVisible();
  await expect(row).toContainText("ended");
});

test("a student cannot open another student's session", async ({ page, browser }) => {
  await register(page, newStudent("owner"));
  await startSession(page, "Type instead");
  const theirs = page.url();

  const intruder = await (await browser.newContext()).newPage();
  await register(intruder, newStudent("intruder"));
  await intruder.goto(theirs);
  // The same answer as for a session that does not exist: no hint that this one does.
  await expect(intruder.getByText("Session not found")).toBeVisible();
  await intruder.context().close();
});
