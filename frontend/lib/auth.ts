// Client-side session helpers.
//
// The token is kept in sessionStorage for this browser tab only. The backend is the authority:
// it validates the signature, issuer, audience, and expiry on every request. Decoding the payload
// here is for display and navigation only and does NOT verify anything.
//
// TODO(sso): replace the paste-a-token sign-in with the enterprise OIDC authorization-code flow
// (PKCE) once the IdP client is registered. Requires SSO configuration (not available here).

export const TOKEN_KEY = "lor.accessToken";
export const ROLE_CLAIM = "roles";

export type Session = {
  token: string;
  subject: string;
  email?: string;
  roles: string[];
  expiresAt?: number;
  permissions?: string[];
};

export function decodeClaims(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"))
        .join(""),
    );
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function sessionFromToken(token: string): Session | null {
  if (token.startsWith("session:")) {
    try {
      const session = JSON.parse(token.slice(8)) as Session;
      return session.expiresAt && session.expiresAt < Date.now()
        ? null
        : session;
    } catch {
      return null;
    }
  }
  const claims = decodeClaims(token);
  if (!claims || typeof claims.sub !== "string") return null;
  const raw = claims[ROLE_CLAIM];
  const roles = Array.isArray(raw)
    ? raw.filter((r): r is string => typeof r === "string")
    : [];
  const exp = typeof claims.exp === "number" ? claims.exp * 1000 : undefined;
  if (exp && exp < Date.now()) return null;
  return {
    token,
    subject: claims.sub,
    email: typeof claims.email === "string" ? claims.email : undefined,
    roles,
    expiresAt: exp,
  };
}

const SESSION_EVENT = "lor:session-changed";

/** Subscribe to sign-in/out changes in this tab (and other tabs via the storage event). */
export function subscribeToSession(callback: () => void): () => void {
  window.addEventListener(SESSION_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(SESSION_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

/** Returns the raw stored token string or null. A primitive, so it is safe as a snapshot. */
export function readStoredToken(): string | null {
  try {
    const verified = sessionStorage.getItem("lor.verifiedSession");
    return verified ? `session:${verified}` : sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.removeItem("lor.verifiedSession");
  } catch {
    // Storage can be unavailable (private mode, blocked). The user will be asked to sign in again.
  }
  window.dispatchEvent(new Event(SESSION_EVENT));
}

export function loadSession(): Session | null {
  try {
    const token = readStoredToken();
    return token ? sessionFromToken(token) : null;
  } catch {
    return null;
  }
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem("lor.verifiedSession");
  } catch {
    // ignore
  }
  window.dispatchEvent(new Event(SESSION_EVENT));
}

export function hasAnyRole(
  session: Session | null,
  required: string[],
): boolean {
  if (!session) return false;
  const aliases: Record<string, string> = {
    Admin: "Super Administrator",
    Contributor: "Content Creator",
  };
  const roles = session.roles.map((r) => aliases[r] || r);
  if (roles.includes("Super Administrator")) return true;
  if (
    roles.includes("Repository Administrator") &&
    required.some((r) => r !== "Super Administrator")
  )
    return true;
  if (required.includes("Learner") && roles.length > 0) return true;
  return required.some((r) => roles.includes(aliases[r] || r));
}

export function saveVerifiedSession(
  data: {
    subject: string;
    email?: string;
    roles: string[];
    permissions: string[];
    expires_at?: string;
  },
  token = "",
) {
  const session: Session = {
    subject: data.subject,
    email: data.email,
    roles: data.roles,
    permissions: data.permissions,
    token,
    expiresAt: data.expires_at ? Date.parse(data.expires_at) : undefined,
  };
  const value = JSON.stringify(session);
  if (sessionStorage.getItem("lor.verifiedSession") === value) return;
  sessionStorage.setItem("lor.verifiedSession", value);
  window.dispatchEvent(new Event(SESSION_EVENT));
}

export function can(session: Session | null, permission: string) {
  return !!session?.permissions?.some((p) => p === "*" || p === permission);
}
