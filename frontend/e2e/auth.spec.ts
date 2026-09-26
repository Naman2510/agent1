import { expect, test } from "@playwright/test";

import { newStudent, register, signIn } from "./support/stack";

test("a new student registers, signs out and signs back in", async ({ page }) => {
  const student = newStudent("auth");
  await register(page, student);
  await expect(page.getByText("No conversations yet")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  await signIn(page, student);
  await expect(page.getByRole("heading", { name: `Namaste, ${student.name}` })).toBeVisible();
});

test("a reload keeps the student signed in, from a cookie page script cannot read", async ({
  page,
}) => {
  const student = newStudent("reload");
  await register(page, student);

  const cookie = (await page.context().cookies()).find((c) => c.name === "vaanios_refresh");
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Strict", path: "/api/auth" });
  expect(await page.evaluate(() => document.cookie)).not.toContain("vaanios_refresh");

  await page.reload();
  await expect(page.getByRole("heading", { name: `Namaste, ${student.name}` })).toBeVisible();
});

test("a failed sign-in does not say whether the account exists", async ({ page }) => {
  const student = newStudent("wrongpw");
  await register(page, student);
  await page.getByRole("button", { name: "Sign out" }).click();

  const refusal = page.getByText("That email and password don't match.");
  await signIn(page, { ...student, password: "not-the-password-at-all" });
  await expect(refusal).toBeVisible();

  // A fresh form, so the second answer cannot be the first one still showing.
  await page.reload();
  await expect(refusal).toHaveCount(0);
  await signIn(page, { ...student, email: `nobody-${student.email}` });
  await expect(refusal).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test("a signed-out visitor is sent to sign in, then on to the page they asked for", async ({
  page,
}) => {
  const student = newStudent("next");
  await register(page, student);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  const wanted = `/sessions/${crypto.randomUUID()}`;
  await page.goto(wanted);
  await expect(page).toHaveURL(`/login?next=${encodeURIComponent(wanted)}`);

  await signIn(page, student);
  await expect(page).toHaveURL(wanted);
  // Nobody's session: the backend answers 404, and the page says so.
  await expect(page.getByText("Session not found")).toBeVisible();
});
