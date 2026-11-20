"use client";

import Link from "@/components/Link";
import { ObjectAccess } from "@/components/ObjectAccess";
import { useEffect, useState, useSyncExternalStore } from "react";
import { apiBlob, apiFetch, postJson, putJson } from "@/lib/api";
import {
  hasAnyRole,
  readStoredToken,
  sessionFromToken,
  subscribeToSession,
} from "@/lib/auth";

type Metadata = {
  title: string;
  description?: string | null;
  subject?: string | null;
  language?: string | null;
  keywords: string[];
  license?: string | null;
};
type Detail = {
  id: string;
  title: string;
  status: string;
  created_by: string;
  metadata: Metadata | null;
  versions: {
    version_number: number;
    original_filename: string;
    size_bytes: number;
  }[];
};

export default function ObjectDetailPage() {
  const token = useSyncExternalStore(
    subscribeToSession,
    readStoredToken,
    () => null,
  );
  const session = token ? sessionFromToken(token) : null;
  const [detail, setDetail] = useState<Detail | null>(null);
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) return;
    apiFetch<Detail>(`/v1/content/${encodeURIComponent(id)}`)
      .then((data) => {
        if (alive) {
          setDetail(data);
          setMetadata(data.metadata || { title: data.title, keywords: [] });
        }
      })
      .catch((err) => {
        if (alive)
          setError(
            err instanceof Error ? err.message : "Unable to load object",
          );
      });
    return () => {
      alive = false;
    };
  }, [token]);
  async function run(action: () => Promise<void>, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      setMessage(success);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }
  if (!detail)
    return (
      <div>
        <h1 className="text-2xl font-semibold">Learning object</h1>
        {error ? (
          <p role="alert">{error}</p>
        ) : (
          <p>
            Select an object from{" "}
            <Link className="underline" href="/search">
              the library
            </Link>
            , collections or favorites.
          </p>
        )}
      </div>
    );
  const latest = detail.versions[detail.versions.length - 1];
  return (
    <article className="space-y-5">
      {hasAnyRole(session, ["Contributor"]) && (detail.created_by === session?.subject || hasAnyRole(session, ["Admin"])) && <ObjectAccess id={detail.id} />}
      <p>
        <Link href="/search">Content Library</Link> / {detail.title}
      </p>
      <h1 className="text-3xl font-semibold">{detail.title}</h1>
      <p>
        {detail.status} · Author: {detail.created_by} · Version{" "}
        {latest?.version_number}
      </p>
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="text-green-800">
          {message}
        </p>
      )}
      <p>
        {detail.metadata?.description || "No description has been provided."}
      </p>
      <div className="flex flex-wrap gap-4">
        <button
          disabled={busy || !latest}
          className="rounded bg-blue-700 p-3 text-white"
          onClick={() =>
            void run(async () => {
              const blob = await apiBlob(`/v1/content/${detail.id}/download`);
              const url = URL.createObjectURL(blob);
              const anchor = document.createElement("a");
              anchor.href = url;
              anchor.download = latest.original_filename;
              anchor.click();
              setTimeout(() => URL.revokeObjectURL(url), 1000);
            }, "Download prepared.")
          }
        >
          Download ({latest?.size_bytes.toLocaleString()} bytes)
        </button>
        <button
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await putJson(`/v1/favorites/${detail.id}`, {
                folder: "AI in Education",
              });
            }, "Saved to AI in Education favorites.")
          }
        >
          Add to Favorites
        </button>
        <button
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await navigator.clipboard.writeText(window.location.href);
            }, "Link copied. Recipients need repository access.")
          }
        >
          Copy share link
        </button>
        <Link href="/collections">Manage collections</Link>
        <Link href="/versioning">Version history</Link>
        {hasAnyRole(session, ["Contributor"]) && detail.status === "draft" && (
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await postJson(`/v1/workflow/${detail.id}/submit`, {});
                setDetail({ ...detail, status: "submitted" });
              }, "Submitted for review.")
            }
          >
            Submit for review
          </button>
        )}
      </div>
      <section className="rounded border bg-white p-5">
        <h2 className="mb-4 text-xl font-semibold">Metadata &amp; Tags</h2>
        {metadata && (
          <form
            className="grid gap-4 md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                const saved = await putJson<Metadata>(
                  `/v1/metadata/${detail.id}`,
                  metadata,
                );
                setMetadata(saved);
                setDetail({ ...detail, title: saved.title, metadata: saved });
              }, "Metadata saved.");
            }}
          >
            {(
              [
                "title",
                "description",
                "subject",
                "language",
                "license",
              ] as const
            ).map((field) => (
              <label className="capitalize" key={field}>
                {field}
                <input
                  className="block w-full rounded border p-2"
                  required={field === "title"}
                  value={metadata[field] || ""}
                  disabled={
                    !hasAnyRole(session, ["Contributor"]) ||
                    !["draft", "rejected"].includes(detail.status)
                  }
                  onChange={(e) =>
                    setMetadata({
                      ...metadata,
                      [field]: e.target.value || null,
                    })
                  }
                />
              </label>
            ))}
            <label>
              Keywords (comma separated)
              <input
                className="block w-full rounded border p-2"
                value={metadata.keywords.join(", ")}
                disabled={
                  !hasAnyRole(session, ["Contributor"]) ||
                  !["draft", "rejected"].includes(detail.status)
                }
                onChange={(e) =>
                  setMetadata({
                    ...metadata,
                    keywords: e.target.value.split(","),
                  })
                }
              />
            </label>
            {hasAnyRole(session, ["Contributor"]) &&
              ["draft", "rejected"].includes(detail.status) && (
                <button
                  disabled={busy}
                  className="rounded bg-blue-700 p-3 text-white"
                >
                  Save metadata
                </button>
              )}
          </form>
        )}
      </section>
    </article>
  );
}
