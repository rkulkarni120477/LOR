"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { apiBlob, apiFetch, postJson, putJson } from "@/lib/api";
import {
  hasAnyRole,
  readStoredToken,
  sessionFromToken,
  subscribeToSession,
} from "@/lib/auth";

type ObjectRow = { id: string; title: string; status: string };
type Collection = {
  id: string;
  name: string;
  description: string;
  visibility: string;
  owner_subject: string;
  items?: ObjectRow[];
};
type Page<T> = { items: T[]; total: number };
type Detail = ObjectRow & {
  versions: {
    version_number: number;
    original_filename: string;
    size_bytes: number;
    created_at: string;
  }[];
};

export function RepositoryWorkspace({
  mode,
}: {
  mode: "collections" | "favorites" | "versioning";
}) {
  const [objects, setObjects] = useState<ObjectRow[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [favorites, setFavorites] = useState<ObjectRow[]>([]);
  const [folders, setFolders] = useState<string[]>([]);
  const [folder, setFolder] = useState("AI in Education");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState("private");
  const [selected, setSelected] = useState("");
  const [active, setActive] = useState<Collection | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const token = useSyncExternalStore(
    subscribeToSession,
    readStoredToken,
    () => null,
  );
  const session = token ? sessionFromToken(token) : null;
  const canEdit = hasAnyRole(session, ["Contributor"]);
  const ownsCollection =
    active &&
    (active.owner_subject === session?.subject ||
      hasAnyRole(session, ["Admin"]));

  const refresh = useCallback(async () => {
    if (mode === "collections") {
      const data = await apiFetch<Page<Collection>>(
        `/v1/collections?page=${page}`,
      );
      setCollections(data.items);
      setTotal(data.total);
    } else if (mode === "favorites") {
      const data = await apiFetch<Page<ObjectRow>>(
        `/v1/favorites?folder=${encodeURIComponent(folder)}&q=${encodeURIComponent(query)}&page=${page}`,
      );
      setFavorites(data.items);
      setTotal(data.total);
    }
  }, [mode, folder, query, page]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      refresh(),
      apiFetch<Page<ObjectRow>>("/v1/content?page_size=100").then((data) => {
        if (alive) setObjects(data.items);
      }),
      apiFetch<{ items: string[] }>("/v1/favorites/folders").then((data) => {
        if (alive) setFolders(data.items);
      }),
    ])
      .catch((err) => {
        if (alive)
          setError(
            err instanceof Error ? err.message : "Unable to load repository",
          );
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [refresh]);

  async function run(action: () => Promise<void>, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      await refresh();
      setMessage(success);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The operation failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveItems(ids: string[]) {
    if (!active) return;
    await putJson(`/v1/collections/${active.id}/items`, { object_ids: ids });
    setActive(await apiFetch<Collection>(`/v1/collections/${active.id}`));
  }

  async function download(id: string, version?: number) {
    const blob = await apiBlob(
      `/v1/content/${id}/download${version ? `?version=${version}` : ""}`,
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download =
      detail?.versions.find((v) => v.version_number === version)
        ?.original_filename || "learning-object";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-[var(--muted)]">
        <Link href="/">Home</Link> / {mode}
      </p>
      <h1 className="text-3xl font-semibold capitalize">{mode}</h1>
      <p>
        {mode === "collections"
          ? "Organize reusable learning objects into shared or private collections."
          : mode === "favorites"
            ? "Keep learning objects in your personal folders."
            : "Inspect file history and restore a previous file as a new draft version."}
      </p>
      {error && (
        <p
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-3 text-red-800"
        >
          {error}
        </p>
      )}
      {message && (
        <p
          role="status"
          className="rounded border border-green-300 bg-green-50 p-3 text-green-800"
        >
          {message}
        </p>
      )}
      {loading && <p role="status">Loading repository…</p>}
      <div className="flex flex-wrap gap-4">
        {mode === "favorites" && (
          <>
            <label>
              Folder
              <select
                className="block rounded border p-2"
                value={folder}
                onChange={(e) => {
                  setFolder(e.target.value);
                  setPage(1);
                }}
              >
                {folders.map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
            </label>
            <label>
              Search favorites
              <input
                className="block rounded border p-2"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(1);
                }}
              />
            </label>
          </>
        )}
        <label>
          Learning object
          <select
            className="block max-w-full rounded border p-2"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">Select an object</option>
            {objects.map((o) => (
              <option key={o.id} value={o.id}>
                {o.title} ({o.status})
              </option>
            ))}
          </select>
          <span className="text-sm text-[var(--muted)]">
            Most recent 100 accessible objects
          </span>
        </label>
        {mode === "favorites" && (
          <button
            className="rounded border px-4"
            disabled={busy || !selected}
            onClick={() =>
              void run(async () => {
                await putJson(`/v1/favorites/${selected}`, { folder });
              }, "Favorite saved.")
            }
          >
            Save favorite
          </button>
        )}
        {mode === "versioning" && (
          <button
            className="rounded border px-4"
            disabled={busy || !selected}
            onClick={() =>
              void run(async () => {
                setDetail(await apiFetch<Detail>(`/v1/content/${selected}`));
              }, "Version history loaded.")
            }
          >
            View history
          </button>
        )}
      </div>

      {mode === "collections" && (
        <>
          {canEdit && (
            <form
              className="flex flex-wrap items-end gap-3 rounded border bg-white p-4"
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  await postJson("/v1/collections", {
                    name,
                    description,
                    visibility,
                  });
                  setName("");
                  setDescription("");
                }, "Collection created.");
              }}
            >
              <label>
                Collection name
                <input
                  required
                  maxLength={255}
                  className="block rounded border p-2"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label>
                Description
                <input
                  maxLength={5000}
                  className="block rounded border p-2"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>
              <label>
                Visibility
                <select
                  className="block rounded border p-2"
                  value={visibility}
                  onChange={(e) => setVisibility(e.target.value)}
                >
                  <option value="private">Private</option>
                  <option value="public">Public</option>
                </select>
              </label>
              <button
                disabled={busy}
                className="rounded bg-blue-700 px-4 py-2 text-white"
              >
                Create collection
              </button>
            </form>
          )}
          <div className="grid gap-3 md:grid-cols-3">
            {collections.map((c) => (
              <button
                key={c.id}
                className="rounded border bg-white p-5 text-left"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    setActive(
                      await apiFetch<Collection>(`/v1/collections/${c.id}`),
                    );
                  }, "Collection opened.")
                }
              >
                <strong>{c.name}</strong>
                <p>{c.description}</p>
                <span className="text-sm">{c.visibility}</span>
              </button>
            ))}
          </div>
          {!loading && collections.length === 0 && (
            <p>No collections available. Create your first collection above.</p>
          )}
          {active && (
            <section className="space-y-3 rounded border bg-white p-5">
              <h2 className="text-xl font-semibold">{active.name}</h2>
              {canEdit && ownsCollection && (
                <div className="flex flex-wrap gap-3">
                  <button
                    className="rounded border p-2"
                    disabled={
                      busy ||
                      !selected ||
                      active.items?.some((i) => i.id === selected)
                    }
                    onClick={() =>
                      void run(
                        () =>
                          saveItems([
                            ...(active.items || []).map((i) => i.id),
                            selected,
                          ]),
                        "Object added.",
                      )
                    }
                  >
                    Add selected object
                  </button>
                  <button
                    className="rounded border p-2"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await putJson(`/v1/collections/${active.id}`, {
                          name: active.name,
                          description: active.description,
                          visibility:
                            active.visibility === "private"
                              ? "public"
                              : "private",
                        });
                        setActive(
                          await apiFetch<Collection>(
                            `/v1/collections/${active.id}`,
                          ),
                        );
                      }, "Visibility updated.")
                    }
                  >
                    Make{" "}
                    {active.visibility === "private" ? "public" : "private"}
                  </button>
                  <button
                    className="rounded border p-2 text-red-700"
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete collection “${active.name}”? Learning objects will be kept.`,
                        )
                      )
                        void run(async () => {
                          await apiFetch(`/v1/collections/${active.id}`, {
                            method: "DELETE",
                          });
                          setActive(null);
                        }, "Collection deleted.");
                    }}
                  >
                    Delete collection
                  </button>
                </div>
              )}
              <ol className="space-y-2">
                {active.items?.map((o, i, items) => (
                  <li
                    className="flex flex-wrap items-center gap-3 rounded border p-3"
                    key={o.id}
                  >
                    <Link
                      className="text-blue-700 underline"
                      href={`/objects?id=${encodeURIComponent(o.id)}`}
                    >
                      {o.title}
                    </Link>
                    <span>{o.status}</span>
                    {canEdit && ownsCollection && (
                      <>
                        <button
                          disabled={busy || i === 0}
                          onClick={() =>
                            void run(async () => {
                              const ids = items.map((item) => item.id);
                              [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
                              await saveItems(ids);
                            }, "Order updated.")
                          }
                        >
                          Move up
                        </button>
                        <button
                          disabled={busy}
                          onClick={() =>
                            void run(
                              () =>
                                saveItems(
                                  items
                                    .filter((item) => item.id !== o.id)
                                    .map((item) => item.id),
                                ),
                              "Object removed.",
                            )
                          }
                        >
                          Remove
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ol>
              {active.items?.length === 0 && (
                <p>This collection has no accessible objects yet.</p>
              )}
            </section>
          )}
        </>
      )}

      {mode === "favorites" && (
        <ul className="space-y-3">
          {favorites.map((o) => (
            <li
              className="flex flex-wrap items-center gap-4 rounded border bg-white p-4"
              key={o.id}
            >
              <Link
                className="text-blue-700 underline"
                href={`/objects?id=${encodeURIComponent(o.id)}`}
              >
                {o.title}
              </Link>
              <span>{o.status}</span>
              <button
                disabled={busy}
                onClick={() =>
                  void run(() => download(o.id), "Download prepared.")
                }
              >
                Download
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await apiFetch(`/v1/favorites/${o.id}`, {
                      method: "DELETE",
                    });
                  }, "Favorite removed.")
                }
              >
                Remove favorite
              </button>
            </li>
          ))}
          {!loading && favorites.length === 0 && (
            <li>No favorites match this folder and search.</li>
          )}
        </ul>
      )}

      {mode === "versioning" && detail && (
        <section className="space-y-4 rounded border bg-white p-5">
          <h2 className="text-xl font-semibold">{detail.title}</h2>
          <p>
            Current state: {detail.status}. Restoring files creates a draft and
            requires a new review. Current metadata is retained.
          </p>
          <ul className="space-y-3">
            {detail.versions.map((v) => (
              <li
                key={v.version_number}
                className="flex flex-wrap items-center gap-4 border-t py-3"
              >
                <strong>Version {v.version_number}</strong>
                <span>{v.original_filename}</span>
                <span>{v.size_bytes.toLocaleString()} bytes</span>
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () => download(detail.id, v.version_number),
                      "Download prepared.",
                    )
                  }
                >
                  Download version
                </button>
                {canEdit && (
                  <button
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Restore version ${v.version_number} as a new draft?`,
                        )
                      )
                        void run(async () => {
                          setDetail(
                            await postJson<Detail>(
                              `/v1/content/${detail.id}/versions/${v.version_number}/restore`,
                              {},
                            ),
                          );
                        }, "New draft version created.");
                    }}
                  >
                    Restore file
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {mode !== "versioning" && (
        <div className="flex items-center gap-4">
          <button
            disabled={busy || page === 1}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </button>
          <span>
            Page {page} · {total} results
          </span>
          <button
            disabled={busy || page * 20 >= total}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
