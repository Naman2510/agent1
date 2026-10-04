"use client";

import { AdminDashboard } from "@/components/AdminDashboard";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/RequireAuth";

export default function AdminPage() {
  return (
    <RequireAuth role="admin">
      {(me) => (
        <AppShell me={me}>
          <AdminDashboard />
        </AppShell>
      )}
    </RequireAuth>
  );
}
