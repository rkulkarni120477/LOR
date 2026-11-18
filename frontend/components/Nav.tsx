"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useSyncExternalStore } from "react";

import {
  clearToken,
  hasAnyRole,
  readStoredToken,
  sessionFromToken,
  subscribeToSession,
} from "@/lib/auth";

// Role-aware navigation. This only hides links for convenience; the backend enforces every route.
const LINKS: { href: string; label: string; roles: string[] }[] = [
  { href: "/search", label: "Search", roles: ["Learner", "Contributor", "Reviewer"] },
  { href: "/contribute", label: "Contribute", roles: ["Contributor"] },
  { href: "/review", label: "Review", roles: ["Reviewer"] },
  { href: "/reports", label: "Reports", roles: ["Admin"] },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const token = useSyncExternalStore(subscribeToSession, readStoredToken, () => null);
  const session = useMemo(() => (token ? sessionFromToken(token) : null), [token]);

  function signOut() {
    clearToken();
    router.push("/login");
  }

  return (
    <header className="border-b border-[var(--border)] bg-[var(--background)]">
      <nav
        aria-label="Main"
        className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3 sm:px-6"
      >
        <Link href="/search" className="font-semibold text-[var(--accent)]">
          LOR
        </Link>
        <ul className="flex flex-wrap gap-3 text-sm">
          {LINKS.filter((link) => hasAnyRole(session, link.roles)).map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className={
                  pathname.startsWith(link.href)
                    ? "font-medium text-[var(--accent)]"
                    : "text-[var(--muted)] hover:text-[var(--foreground)]"
                }
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
        <div className="ml-auto text-sm">
          {session ? (
            <span className="flex items-center gap-3">
              <span className="text-[var(--muted)]">
                {session.email ?? session.subject} · {session.roles.join(", ") || "no roles"}
              </span>
              <button onClick={signOut} className="underline">
                Sign out
              </button>
            </span>
          ) : (
            <Link href="/login" className="underline">
              Sign in
            </Link>
          )}
        </div>
      </nav>
    </header>
  );
}
