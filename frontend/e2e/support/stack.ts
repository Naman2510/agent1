import { execFileSync, execSync } from "node:child_process";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

/**
 * Where the stack under test is. Unset, playwright.config.ts starts one from source on these
 * ports; set E2E_WEB_URL and E2E_API_URL to drive one that is already running (CI points them at
 * the Docker Compose stack, so the shipped images are what gets tested).
 */
export const externalStack = process.env.E2E_WEB_URL !== undefined;
export const WEB_URL = (process.env.E2E_WEB_URL ?? "http://localhost:3100").replace(/\/$/, "");
export const API_URL = (process.env.E2E_API_URL ?? "http://localhost:8100").replace(/\/$/, "");

export const REPO = path.resolve(__dirname, "../../..");
export const BACKEND = path.join(REPO, "backend");
export const PYTHON = process.env.E2E_PYTHON ?? path.join(BACKEND, "venv", "bin", "python");

/** What the scripted LLM says to everything (backend/app/providers/llm/fake.py). */
export const FAKE_REPLY = "This is a fake mentor response.";
/** What the fake STT hears in any utterance (backend/app/providers/stt/fake.py). */
export const FAKE_TRANSCRIPT = "Kirchhoff ka voltage law samjhao";

export interface Student {
  name: string;
  email: string;
  password: string;
}

/** A student nobody has registered yet: every test makes its own, so tests share no state. */
export function newStudent(tag: string): Student {
  const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  return {
    name: `E2E ${tag}`,
    email: `e2e-${tag}-${id}@example.com`,
    password: "correct-horse-battery-staple",
  };
}

export async function register(page: Page, student: Student): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("Your name").fill(student.name);
  await page.getByLabel("Email").fill(student.email);
  await page.getByLabel("Password").fill(student.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: `Namaste, ${student.name}` })).toBeVisible();
}

export async function signIn(page: Page, student: Student): Promise<void> {
  await page.getByLabel("Email").fill(student.email);
  await page.getByLabel("Password").fill(student.password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/**
 * Grant the admin role the way the README tells an operator to: the promote script, run by
 * someone with shell access to the deployment — there is deliberately no HTTP route for it.
 * E2E_PROMOTE_ADMIN is that command for a stack these tests did not start.
 */
export function promoteToAdmin(email: string): void {
  const command = process.env.E2E_PROMOTE_ADMIN;
  if (command) {
    // The address is one newStudent() made: letters, digits, "-", "@" and ".".
    execSync(`${command} ${email}`, { cwd: REPO, stdio: "pipe" });
  } else {
    execFileSync(PYTHON, ["scripts/promote_admin.py", email], { cwd: BACKEND, stdio: "pipe" });
  }
}

/** A newly started session's page, by the button the home page offers for it. */
export async function startSession(page: Page, how: "Start talking" | "Type instead") {
  await page.getByRole("button", { name: how }).click();
  await page.waitForURL(/\/sessions\/[0-9a-f-]{36}$/);
}
