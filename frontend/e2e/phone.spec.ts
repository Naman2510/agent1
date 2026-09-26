import { expect, test, type Page } from "@playwright/test";

import { newStudent, promoteToAdmin, register, startSession } from "./support/stack";
import { startTalking, statusLine } from "./support/voice";

// Most students will be on a phone. 390 px is a common small width (iPhone 12–15).
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

async function expectNoSidewaysScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(0);
}

test("every page fits a phone screen", async ({ page }) => {
  await page.goto("/register");
  await expectNoSidewaysScroll(page);

  const student = newStudent("phone");
  await register(page, student);
  await expectNoSidewaysScroll(page);

  // The voice controls at their widest: Stop, Mute and Hang up all showing.
  await startSession(page, "Start talking");
  await startTalking(page);
  await expectNoSidewaysScroll(page);
  await page.getByLabel("Or type your question").fill("Norton theorem samjhao");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(statusLine(page)).toHaveText("Speaking");
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  await expectNoSidewaysScroll(page);
  // The status is the one thing a student must be able to read; the buttons must not squeeze it.
  const status = await statusLine(page).boundingBox();
  expect(status?.width ?? 0).toBeGreaterThanOrEqual(100);
  await expect(statusLine(page)).toHaveText("Listening — ask anything");
  await page.getByRole("button", { name: "Hang up" }).click();

  await page.getByRole("link", { name: "← All sessions" }).click();
  await expectNoSidewaysScroll(page);

  promoteToAdmin(student.email);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Admin", level: 1 })).toBeVisible();
  await expectNoSidewaysScroll(page);
});
