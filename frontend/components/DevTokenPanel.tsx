"use client";

import { useEffect, useState } from "react";

// DEV ONLY. The backend registers /api/v1/dev/tokens only when ENV=development.
// When the endpoint is absent (any other environment), this panel renders nothing.

type DevTokensResponse = { warning: string; tokens: Record<string, string> };

export function DevTokenPanel({ onUse }: { onUse: (token: string) => void }) {
  const [tokens, setTokens] = useState<Record<string, string> | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/dev/tokens", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return null;
        return (await response.json()) as DevTokensResponse;
      })
      .then((body) => {
        if (!cancelled && body) setTokens(body.tokens);
      })
      .catch(() => {
        // Backend unreachable or endpoint absent: keep the panel hidden.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!tokens) return null;

  async function copy(role: string, token: string) {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(role);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  }

  return (
    <div className="space-y-3 rounded border border-amber-500 bg-amber-50 p-4 text-sm text-amber-950 dark:bg-amber-950/30 dark:text-amber-100">
      <p className="font-medium">Development tokens (local only, valid 24 hours)</p>
      {Object.entries(tokens).map(([role, token]) => (
        <div key={role} className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="w-24 font-medium">{role}</span>
            <button
              type="button"
              onClick={() => copy(role, token)}
              className="rounded border border-current px-2 py-0.5 text-xs"
            >
              {copied === role ? "Copied" : "Copy"}
            </button>
            <button
              type="button"
              onClick={() => onUse(token)}
              className="rounded border border-current px-2 py-0.5 text-xs"
            >
              Use
            </button>
          </div>
          <textarea
            readOnly
            value={token}
            aria-label={`${role} token`}
            rows={2}
            onFocus={(e) => e.currentTarget.select()}
            className="w-full rounded border border-amber-700/40 bg-white/70 p-1 font-mono text-[10px] text-black dark:bg-black/40 dark:text-amber-100"
          />
        </div>
      ))}
    </div>
  );
}
