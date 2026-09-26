"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button, Card, ErrorText, Field } from "@/components/ui";
import { describeError } from "@/lib/api/errors";
import { safeNext, useAuth } from "@/lib/auth/AuthProvider";

// The backend's own rule (app/schemas/auth.py); checked here only to save a round trip.
const MIN_PASSWORD = 12;

export function RegisterForm({ next }: { next?: string }) {
  const { register, state } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (state.status === "authenticated") router.replace(safeNext(next));
  }, [state.status, next, router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const semester = String(form.get("semester") ?? "").trim();
    setPending(true);
    setError(null);
    try {
      await register({
        display_name: String(form.get("display_name")),
        email: String(form.get("email")),
        password: String(form.get("password")),
        semester: semester ? Number(semester) : null,
      });
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <h1 className="text-lg font-semibold">Create your account</h1>
      <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-4">
        <Field
          id="display_name"
          name="display_name"
          label="Your name"
          autoComplete="name"
          maxLength={120}
          required
        />
        <Field id="email" name="email" type="email" label="Email" autoComplete="email" required />
        <Field
          id="password"
          name="password"
          type="password"
          label="Password"
          autoComplete="new-password"
          minLength={MIN_PASSWORD}
          maxLength={128}
          hint={`At least ${MIN_PASSWORD} characters.`}
          required
        />
        <Field
          id="semester"
          name="semester"
          type="number"
          label="Semester (optional)"
          min={1}
          max={12}
          inputMode="numeric"
        />
        <ErrorText>{error}</ErrorText>
        <Button type="submit" disabled={pending}>
          {pending ? "Creating account…" : "Create account"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-muted">
        Already have an account?{" "}
        <Link
          href={next ? `/login?next=${encodeURIComponent(next)}` : "/login"}
          className="font-medium text-accent hover:underline"
        >
          Sign in
        </Link>
      </p>
    </Card>
  );
}
