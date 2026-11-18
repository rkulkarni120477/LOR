"use client";

import { useEffect, useState } from "react";

import { PackagePreview } from "@/components/PackagePreview";
import { ApiError, apiFetch, postJson } from "@/lib/api";

type Item = { id: string; title: string; status: string; created_by: string };
type Page = { items: Item[]; total: number };

export default function ReviewPage() {
  const [queue, setQueue] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Item | null>(null);
  const [comment, setComment] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Page>("/v1/content?status=submitted&page_size=50")
      .then((page) => {
        if (!cancelled) setQueue(page.items);
      })
      .catch((err: unknown) => {
        if (!cancelled) setMessage(err instanceof ApiError ? err.message : "Could not load queue");
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  async function decide(decision: "approve" | "reject") {
    if (!selected) return;
    try {
      await postJson(`/v1/workflow/${selected.id}/decision`, {
        decision,
        comment: comment || null,
      });
      setMessage(`${decision === "approve" ? "Approved" : "Rejected"}: ${selected.title}`);
      setSelected(null);
      setComment("");
      setReloadKey((k) => k + 1);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Decision failed");
    }
  }

  return (
    <div className="space-y-8">
    <div className="grid gap-6 md:grid-cols-[1fr_1fr]">
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold">Review queue</h1>
        {message && <p className="text-sm">{message}</p>}
        {queue.length === 0 && <p className="text-sm text-[var(--muted)]">Nothing to review.</p>}
        <ul className="space-y-2">
          {queue.map((item) => (
            <li key={item.id}>
              <button
                onClick={() => setSelected(item)}
                aria-pressed={selected?.id === item.id}
                className="w-full rounded border border-[var(--border)] p-3 text-left text-sm"
              >
                <span className="font-medium">{item.title}</span>
                <span className="block text-xs text-[var(--muted)]">Submitted by {item.created_by}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="font-medium">Decision</h2>
        {selected ? (
          <div className="space-y-3">
            <p className="text-sm">{selected.title}</p>
            <label className="block text-sm">
              Comment (required to reject)
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={4}
                className="mt-1 w-full rounded border border-[var(--border)] bg-transparent p-2"
              />
            </label>
            <div className="flex gap-2">
              <button onClick={() => decide("approve")} className="rounded bg-[var(--accent)] px-4 py-2 text-sm text-white">
                Approve
              </button>
              <button
                onClick={() => decide("reject")}
                disabled={!comment.trim()}
                className="rounded border border-red-600 px-4 py-2 text-sm text-red-600 disabled:opacity-40"
              >
                Reject
              </button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">Select an item from the queue.</p>
        )}
      </section>
    </div>
    {selected && <PackagePreview key={selected.id} loId={selected.id} />}
    </div>
  );
}
