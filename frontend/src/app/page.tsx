"use client";

import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";
import { SessionList, StartSession } from "@/components/SessionList";

export default function HomePage() {
  return (
    <RequireAuth>
      {(me) => (
        <AppShell me={me}>
          <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h1 className="text-xl font-semibold">
                Namaste, {me.student?.display_name ?? me.email}
              </h1>
              <p className="mt-1 text-sm text-muted">Pick up where you left off, or start fresh.</p>
            </div>
            <StartSession />
          </div>
          <SessionList />
        </AppShell>
      )}
    </RequireAuth>
  );
}
