"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { saveToken, sessionFromToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const session = sessionFromToken(token.trim());
    if (!session) {
      setError("That token is malformed or expired.");
      return;
    }
    saveToken(token.trim());
    router.push("/search");
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <div className="rounded border border-[var(--border)] p-4 text-sm">
        <p className="font-medium">Enterprise SSO: not configured in this build.</p>
        <p className="mt-1 text-[var(--muted)]">
          Requires an OIDC client registration with your identity provider. Until then, paste a
          bearer token. In local development, generate one with{" "}
          <code>ENV=development python scripts/dev_token_issuer.py</code>.
        </p>
      </div>
      <form onSubmit={submit} className="space-y-3">
        <label className="block text-sm font-medium" htmlFor="token">
          Bearer token
        </label>
        <textarea
          id="token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          rows={5}
          className="w-full rounded border border-[var(--border)] bg-transparent p-2 font-mono text-xs"
          required
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          className="rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white"
        >
          Continue
        </button>
      </form>
    </div>
  );
}
