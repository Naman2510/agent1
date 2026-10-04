"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth/AuthProvider";
import type { Me } from "@/lib/api/types";

export function AppShell({ me, children }: { me: Me; children: ReactNode }) {
  const { logout } = useAuth();
  const pathname = usePathname();
  const links = [
    { href: "/", label: "Sessions" },
    ...(me.role === "admin" ? [{ href: "/admin", label: "Admin" }] : []),
  ];

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
          <Link href="/" className="text-base font-semibold tracking-tight">
            Vaani<span className="text-accent">OS</span>
          </Link>
          <nav className="flex gap-4 text-sm">
            {links.map((link) => {
              const active =
                link.href === "/" ? pathname === "/" || pathname.startsWith("/sessions") : pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={active ? "font-medium text-foreground" : "text-muted hover:text-foreground"}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="hidden text-muted sm:inline">
              {me.student?.display_name ?? me.email}
            </span>
            <button
              type="button"
              onClick={() => void logout()}
              className="rounded-md px-2 py-1 text-muted hover:bg-background hover:text-foreground"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-4 py-6">{children}</main>
    </div>
  );
}
