import { expect, test, type Page } from "@playwright/test";

import { FAKE_REPLY, newStudent, promoteToAdmin, register, startSession } from "./support/stack";
import { transcript } from "./support/voice";

test("a student is kept out of the admin page", async ({ page }) => {
  await register(page, newStudent("student"));
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Admins only" })).toBeVisible();
});

/** A stat tile's number, by its label. */
async function tileValue(page: Page, label: string): Promise<number> {
  const value = page.getByText(label, { exact: true }).locator("xpath=following-sibling::p[1]");
  return Number((await value.innerText()).replace(/,/g, ""));
}

test("an admin sees the dashboard, counting what just happened", async ({ page }) => {
  const admin = newStudent("admin");
  await register(page, admin);
  // Something for the dashboard to count, with its timing.
  await startSession(page, "Type instead");
  await page.getByLabel("Ask your question").fill("Thevenin theorem kya hai?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(transcript(page).nth(1)).toContainText(FAKE_REPLY);

  promoteToAdmin(admin.email);
  // The role is read from the database on every request, so a reload is all it takes.
  await page.reload();
  await page.getByRole("link", { name: "Admin" }).click();
  await expect(page.getByRole("heading", { name: "Admin", level: 1 })).toBeVisible();

  for (const section of ["Right now", "Speed and reliability", "Tools", "Learning"]) {
    await expect(page.getByRole("heading", { name: section, level: 2 })).toBeVisible();
  }
  // Evaluation comes from runs the evaluation runner recorded. A fresh stack has none, and says
  // so; a database with runs shows them. Either way, never an invented number.
  for (const section of ["Evaluation", "Experiments"]) {
    await expect(page.getByRole("heading", { name: section, level: 2 })).toBeVisible();
  }
  await expect(
    page
      .getByText("No evaluation run has been recorded in this database.", { exact: false })
      .or(page.getByRole("columnheader", { name: "Recorded" })),
  ).toBeVisible();
  expect(await tileValue(page, "Students")).toBeGreaterThanOrEqual(1);
  expect(await tileValue(page, "Sessions, all time")).toBeGreaterThanOrEqual(1);
  expect(await tileValue(page, "Messages, all time")).toBeGreaterThanOrEqual(2);
  // A turn with recorded timing exists now, so this is a measurement, not "not measured".
  await expect(page.getByText("Average first token").locator("..")).not.toContainText(
    "Not measured",
  );
  // Nothing records speech-recognition failures yet, and the page says so rather than showing 0.
  await expect(page.getByText("Speech-recognition failures").locator("..")).toContainText(
    "Not measured",
  );

  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("button", { name: "Refresh" })).toBeEnabled();
  await expect(page.getByText(/^Updated /)).toBeVisible();
});
