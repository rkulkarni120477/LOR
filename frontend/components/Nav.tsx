"use client";

import Link from "@/components/Link";
import { useLocation, useNavigate } from "react-router-dom";
import { useMemo, useSyncExternalStore, type ReactNode } from "react";

import { Icon, type IconName } from "@/components/Icon";
import {
  clearToken,
  hasAnyRole,
  readStoredToken,
  sessionFromToken,
  subscribeToSession,
  can,
} from "@/lib/auth";
import { apiFetch } from "@/lib/api";

const LINKS: { href: string; label: string; icon: IconName; roles?: string[] }[] = [
  { href: "/", label: "Home", icon: "home" },
  {
    href: "/search",
    label: "Content Library",
    icon: "library",
    roles: ["Learner", "Contributor", "Reviewer"],
  },
  { href: "/library", label: "Library", icon: "library", roles: ["Learner", "Contributor", "Reviewer"] },
  { href: "/contribute", label: "Create", icon: "plus", roles: ["Contributor"] },
  { href: "/contribute", label: "Upload", icon: "upload", roles: ["Contributor"] },
  { href: "/review", label: "Workflows", icon: "workflow", roles: ["Reviewer"] },
  { href: "/collections", label: "Collections", icon: "folder", roles: ["Learner", "Contributor", "Reviewer"] },
  { href: "/versioning", label: "Versioning", icon: "clock", roles: ["Contributor", "Reviewer"] },
  { href: "/favorites", label: "Favorites", icon: "book", roles: ["Learner", "Contributor", "Reviewer"] },
  { href: "/reports", label: "Reports & Analytics", icon: "chart", roles: ["Admin"] },
];

export function Nav({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const token = useSyncExternalStore(subscribeToSession, readStoredToken, () => null);
  const session = useMemo(() => (token ? sessionFromToken(token) : null), [token]);
  const displayName = session?.email?.split("@")[0] ?? session?.subject ?? "Guest";
  const initials = displayName
    .split(/[ ._-]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  async function signOut() {
    try { await apiFetch("/v1/auth/logout", {method: "POST"}); }
    finally {clearToken(); navigate("/login");}
  }

  return (
    <>
      <header className="app-header">
        <Link href="/" className="brand-lockup" aria-label="ELOR home">
          <span className="brand-symbol">
            <Icon name="layers" size={29} />
          </span>
          <span className="brand-name">ELOR</span>
        </Link>
        <span className="header-divider" aria-hidden="true" />
        <span className="header-title">Enterprise Learning Object Repository</span>
        <div className="header-actions">
          <Link className="header-icon" href="/search" aria-label="Open content library">
            <Icon name="search" size={22} />
          </Link>
          {session && hasAnyRole(session, ["Reviewer"]) && (
            <Link className="header-icon" href="/review" aria-label="Review queue">
              <Icon name="bell" size={22} />
            </Link>
          )}
          <span className="profile-avatar" aria-hidden="true">
            {initials || "G"}
          </span>
          <div className="profile-copy">
            <span className="profile-name">{displayName}</span>
            <span className="profile-role">{session?.roles[0] ?? "Guest"}</span>
          </div>
          {session ? (
            <button type="button" className="profile-action" onClick={signOut}>
              Sign out
            </button>
          ) : (
            <Link href="/login" className="profile-action">
              Sign in
            </Link>
          )}
        </div>
      </header>
      <div className="app-shell">
        <aside className="app-sidebar">
          <nav aria-label="Main navigation">
            {LINKS.filter((link) => !link.roles || hasAnyRole(session, link.roles)).map(
              (link, index) => {
                const active =
                  link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
                return (
                  <Link
                    key={`${link.href}-${link.label}`}
                    href={link.href}
                    className={`sidebar-link${active ? " active" : ""}${index === 0 ? " home-link" : ""}`}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon name={link.icon} size={19} />
                    <span>{link.label}</span>
                  </Link>
                );
              },
            )}
          </nav>
          {can(session, "organization.manage") && <Link href="/administration" className={`sidebar-link${pathname === "/administration" ? " active" : ""}`}><Icon name="users" size={19} /><span>Administration</span></Link>}
          <div className="sidebar-bottom">
            <div className="storage-card">
              <span className="storage-icon">
                <Icon name="layers" size={21} />
              </span>
              <div>
                <strong>Learning library</strong>
                <span>Shared content workspace</span>
              </div>
            </div>
          </div>
        </aside>
        <main className="app-main">{children}</main>
      </div>
    </>
  );
}
