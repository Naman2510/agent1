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

test("an answer in the history shows the tools it used and the sources it cited", async ({
  page,
}) => {
  await register(page, newStudent("sources"));
  await startSession(page, "Type instead");
  await page.getByLabel("Ask your question").fill(QUESTION);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(transcript(page)).toHaveCount(2);

  // The scripted LLM never calls a tool, so its answer has no sources. Add them to the real stored
  // answer on its way to the page, in the shape the backend's tests pin
  // (backend/tests/integration/test_chat_turn.py): this checks the rendering, not the retrieval.
  await page.route(/\/v1\/sessions\/[0-9a-f-]+\/messages/, async (route) => {
    const response = await route.fetch();
    const messages = (await response.json()) as Record<string, unknown>[];
    messages[1] = {
      ...messages[1],
      tool_activity: [
        { tool_name: "search_knowledge", ok: true },
        { tool_name: "get_student_progress", ok: false },
      ],
      citations: [
        {
          ref: "[1]",
          document_title: "KVL Notes",
          heading_path: "Unit 7 › 7.1 KVL",
          section: "7.1",
          page_start: 12,
          page_end: 13,
        },
      ],
    };
    await route.fulfill({ response, json: messages });
  });
  await page.reload();

  const answer = transcript(page).nth(1);
  await expect(answer.getByRole("list", { name: "Sources" })).toHaveText(
    "[1] KVL Notes — Unit 7 › 7.1 KVL — pp. 12–13",
  );
  const tools = answer.getByRole("list", { name: "What the mentor did" });
  await expect(tools).toContainText("Searched your course material");
  await expect(tools).toContainText("Checked your progress (failed)");
  // The student's own message carries neither.
  await expect(transcript(page).nth(0).getByRole("list")).toHaveCount(0);
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
