"use client";

import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Stack } from "@mui/material";
import { apiFetch } from "@/lib/api";

import { DevTokenPanel } from "@/components/DevTokenPanel";
import { saveToken, saveVerifiedSession, sessionFromToken } from "@/lib/auth";

export default function LoginPage() {
  const navigate = useNavigate();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const configuration = useQuery({
    queryKey: ["auth-config"],
    queryFn: () =>
      apiFetch<{
        sso_enabled: boolean;
        development_login: boolean;
      }>("/v1/auth/config"),
  });

  async function signInWith(value: string) {
    const trimmed = value.trim();
    const session = sessionFromToken(trimmed);
    if (!session) {
      setError("That token is malformed or expired.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const identity = await apiFetch<
        Parameters<typeof saveVerifiedSession>[0]
      >("/v1/auth/me", {
        headers: { Authorization: `Bearer ${trimmed}` },
      });
      saveToken(trimmed);
      saveVerifiedSession(identity, trimmed);
      navigate("/search");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    void signInWith(token);
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <Stack spacing={2}>
        {configuration.error && (
          <Alert severity="error">{configuration.error.message}</Alert>
        )}
        {new URLSearchParams(window.location.search).has("sso_error") && (
          <Alert severity="error">
            Organization sign-in failed. Please try again.
          </Alert>
        )}
        {configuration.data?.sso_enabled ? (
          <Button variant="contained" component="a" href="/api/v1/auth/login">
            Sign in with Microsoft (academian)
          </Button>
        ) : (
          configuration.data && (
            <Alert severity="info">
              Enterprise sign-in needs identity provider configuration.
            </Alert>
          )
        )}
      </Stack>
      {configuration.data?.development_login && (
        <>
          <DevTokenPanel
            onUse={(value) => {
              setToken(value);
              void signInWith(value);
            }}
          />
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
              disabled={busy}
              type="submit"
              className="rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white"
            >
              Continue
            </button>
          </form>
        </>
      )}
    </div>
  );
}
