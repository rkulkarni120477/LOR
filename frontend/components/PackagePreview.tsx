"use client";

import { useEffect, useState } from "react";

import { ApiError, apiBlob, apiFetch } from "@/lib/api";

// Reviewer preview of an uploaded package. Package content is untrusted: HTML is shown in a
// sandboxed iframe with no scripts, and images are inlined so relative references resolve.

type PackageFile = { path: string; size: number; content_type: string };

export function PackagePreview({ loId }: { loId: string }) {
  const [files, setFiles] = useState<PackageFile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ files: PackageFile[] }>(`/v1/content/${loId}/package/files`)
      .then((result) => {
        if (cancelled) return;
        setFiles(result.files);
        const first = result.files.find((f) => f.path.endsWith(".html") || f.path.endsWith(".htm"));
        setSelected(first?.path ?? result.files[0]?.path ?? null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Preview unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [loId]);

  useEffect(() => {
    if (!selected || !files) return;
    const file = files.find((f) => f.path === selected);
    if (!file) return;
    let cancelled = false;
    let objectUrl: string | null = null;

    async function load() {
      setLoading(true);
      setHtml(null);
      setImageUrl(null);
      try {
        const blob = await apiBlob(`/v1/content/${loId}/package/files/${encodeURI(file!.path)}`);
        if (cancelled) return;
        if (file!.content_type === "text/html") {
          const text = await blob.text();
          const inlined = await inlineImages(text, files!, loId);
          if (!cancelled) setHtml(inlined);
        } else if (file!.content_type.startsWith("image/")) {
          objectUrl = URL.createObjectURL(blob);
          if (!cancelled) setImageUrl(objectUrl);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load file");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selected, files, loId]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!files) return <p className="text-sm text-[var(--muted)]">Loading package...</p>;

  return (
    <section className="space-y-3">
      <h2 className="font-medium">Package preview</h2>
      <div className="grid gap-3 md:grid-cols-[12rem_1fr]">
        <ul className="space-y-1 text-sm">
          {files.map((f) => (
            <li key={f.path}>
              <button
                onClick={() => setSelected(f.path)}
                aria-pressed={selected === f.path}
                className={`break-all text-left ${selected === f.path ? "font-semibold" : "text-[var(--muted)]"}`}
              >
                {f.path}
              </button>
            </li>
          ))}
        </ul>
        <div className="min-h-64 rounded border border-[var(--border)] bg-white">
          {loading && <p className="p-3 text-sm text-[var(--muted)]">Loading...</p>}
          {html !== null && (
            <iframe
              title={`Preview of ${selected}`}
              sandbox=""
              srcDoc={html}
              className="h-96 w-full"
            />
          )}
          {imageUrl && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imageUrl} alt={`Preview of ${selected}`} className="max-h-96 p-3" />
          )}
          {!loading && html === null && !imageUrl && selected && (
            <p className="p-3 text-sm text-[var(--muted)]">
              No inline preview for this file type ({files.find((f) => f.path === selected)?.content_type}).
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

async function inlineImages(html: string, files: PackageFile[], loId: string): Promise<string> {
  const images = files.filter((f) => f.content_type.startsWith("image/"));
  const dataUrls = new Map<string, string>();
  for (const image of images) {
    const blob = await apiBlob(`/v1/content/${loId}/package/files/${encodeURI(image.path)}`);
    dataUrls.set(image.path, await blobToDataUrl(blob));
  }
  return html.replace(/(src=["'])([^"']+)(["'])/g, (match, open: string, src: string, close: string) => {
    const inlined = dataUrls.get(src);
    return inlined ? `${open}${inlined}${close}` : match;
  });
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
