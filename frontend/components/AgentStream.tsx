"use client";

import { useState } from "react";

import { loadSession } from "@/lib/auth";

type Props = {
  /** Path under /api, e.g. "/v1/agents/ask". */
  endpoint: string;
  /** Builds the JSON body from the user's input. */
  buildBody: (input: string) => unknown;
  placeholder?: string;
  submitLabel?: string;
};

/**
 * Reads a Server-Sent Events stream from an agent endpoint and renders tokens as they arrive.
 * Expects frames of the form: `event: token\ndata: {"text":"..."}\n\n` and a final `event: done`.
 */
export function AgentStream({ endpoint, buildBody, placeholder, submitLabel = "Ask" }: Props) {
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    if (!input.trim()) return;
    setOutput("");
    setError(null);
    setRunning(true);
    const session = loadSession();
    try {
      const response = await fetch(`/api${endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...(session?.token ? { Authorization: `Bearer ${session.token}` } : {}),
        },
        body: JSON.stringify(buildBody(input.trim())),
        cache: "no-store",
      });
      if (!response.ok || !response.body) {
        throw new Error(`Request failed (${response.status})`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          handleFrame(frame, setOutput);
          boundary = buffer.indexOf("\n\n");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stream failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-3">
      <form onSubmit={run} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder ?? "Question"}
          className="flex-1 rounded border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={running}
          className="rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {running ? "Working..." : submitLabel}
        </button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {output && (
        <p
          aria-live="polite"
          className="whitespace-pre-wrap rounded border border-[var(--border)] p-3 text-sm"
        >
          {output}
        </p>
      )}
    </div>
  );
}

function handleFrame(frame: string, append: (updater: (prev: string) => string) => void) {
  let eventName = "message";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (eventName === "token" && data) {
    try {
      const parsed = JSON.parse(data) as { text?: string };
      if (parsed.text) append((prev) => prev + parsed.text);
    } catch {
      // ignore malformed frame
    }
  }
}
