"use client";

import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";

export default function HomePage() {
  return (
    <RequireAuth>
      {(me) => (
        <AppShell me={me}>
          <h1 className="text-xl font-semibold">
            Welcome, {me.student?.display_name ?? me.email}
          </h1>
        </AppShell>
      )}
    </RequireAuth>
  );
}
