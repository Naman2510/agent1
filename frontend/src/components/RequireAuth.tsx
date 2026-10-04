"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button, Card, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { Me } from "@/lib/api/types";

/**
 * A client-side gate. It protects nothing on its own — every page's data comes from the backend,
 * which authorises each request — it only keeps signed-out visitors on a page that works for them.
 */
export function RequireAuth({
  children,
  role,
}: {
  children: (me: Me) => ReactNode;
  role?: "admin";
}) {
  const { state, retry } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (state.status === "anonymous") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [state.status, router, pathname]);

  if (state.status === "authenticated") {
    if (role === "admin" && state.me.role !== "admin") {
      return (
        <Centered>
          <Card className="max-w-md">
            <h1 className="text-lg font-semibold">Admins only</h1>
            <p className="mt-2 text-sm text-muted">This page is for VaaniOS administrators.</p>
          </Card>
        </Centered>
      );
    }
    return <>{children(state.me)}</>;
  }
  if (state.status === "unavailable") {
    return (
      <Centered>
        <Card className="max-w-md">
          <h1 className="text-lg font-semibold">Can’t reach VaaniOS</h1>
          <p className="mt-2 text-sm text-muted">
            The service didn’t respond. You’re probably still signed in.
          </p>
          <Button className="mt-4" onClick={retry}>
            Try again
          </Button>
        </Card>
      </Centered>
    );
  }
  return (
    <Centered>
      <Spinner />
    </Centered>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex flex-1 items-center justify-center p-6">{children}</div>;
}
