"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, apiFetch, apiBlob, postJson } from "@/lib/api";
import { loadSession } from "@/lib/auth";

export type UploadResult = {
  id: string;
  title: string;
  status: string;
  scan_status: string | null;
  quarantined: boolean;
  validation: {
    standard: string | null;
    warnings: string[];
    launch_files: string[];
  } | null;
  thumbnail_url: string | null;
};

type UploadStatus = {
  id: string;
  status: "uploading" | "assembled" | "completed" | "aborted" | "rejected";
  part_size: number;
  part_count: number;
  size_bytes: number;
  completed_parts: number[];
  missing_parts: number[];
  learning_object_id: string | null;
};

type PartTarget = { method: string; url: string; headers: Record<string, string>; direct: boolean };

type Phase = "idle" | "uploading" | "paused" | "assembling" | "done" | "duplicate" | "rejected" | "error";

const CONCURRENCY = 3;
const MAX_ATTEMPTS = 5;
const STORAGE_PREFIX = "lor.upload.";

function contentTypeFor(file: File): string {
  if (file.type) return file.type;
  return file.name.toLowerCase().endsWith(".pdf") ? "application/pdf" : "application/zip";
}

/** Stable per-file key, so a reload can resume the same server-side upload. */
function fingerprint(file: File): string {
  return `${STORAGE_PREFIX}${file.name}|${file.size}|${file.lastModified}`;
}

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Storage can be blocked. Resume then starts over, which is still correct.
  }
}

/** Size of one part. Every part is full-sized except the last. */
function partBytes(status: UploadStatus, number: number): number {
  if (number < status.part_count) return status.part_size;
  return status.size_bytes - status.part_size * (status.part_count - 1);
}

function authorizationHeaders(): Record<string, string> {
  const token = loadSession()?.token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function isPausedOrCancelled(error: unknown, signal: AbortSignal): boolean {
  return signal.aborted || (error instanceof DOMException && error.name === "AbortError");
}

export function ResumableUpload({
  onComplete,
  disabled = false,
}: {
  onComplete: (result: UploadResult) => void;
  disabled?: boolean;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [status, setStatus] = useState<UploadStatus | null>(null);
  const [bytesDone, setBytesDone] = useState(0);
  const [partsDone, setPartsDone] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [thumbnail, setThumbnail] = useState<string | null>(null);

  // Run state lives in refs, so the async part loop sees pause and cancel immediately.
  const pausedRef = useRef(false);
  const runningRef = useRef(false);
  const controllers = useRef(new Set<AbortController>());
  const storageKeyRef = useRef<string | null>(null);
  const uploadIdRef = useRef<string | null>(null);
  const fileRef = useRef<File | null>(null);

  // Leaving the page stops any in-flight parts. The server keeps the finished ones for resume.
  useEffect(() => {
    const active = controllers.current;
    return () => {
      pausedRef.current = true;
      active.forEach((c) => c.abort());
    };
  }, []);

  useEffect(() => {
    return () => {
      if (thumbnail) URL.revokeObjectURL(thumbnail);
    };
  }, [thumbnail]);

  function setActiveId(id: string | null) {
    uploadIdRef.current = id;
    setUploadId(id);
  }

  /** One request for one part. S3 targets are presigned, so no credentials are sent to them. */
  async function sendPart(id: string, number: number, blob: Blob, signal: AbortSignal) {
    const target = await apiFetch<PartTarget>(`/v1/uploads/${id}/parts/${number}/url`, { signal });
    if (target.direct) {
      const response = await fetch(target.url, { method: "PUT", body: blob, signal });
      if (!response.ok) throw new ApiError(response.status, `storage rejected part ${number}`);
      const etag = response.headers.get("ETag");
      if (!etag) throw new Error("storage returned no ETag; check the bucket's CORS expose-headers");
      await postJson(`/v1/uploads/${id}/parts/${number}/ack`, { size_bytes: blob.size, etag });
      return;
    }
    const response = await fetch(target.url, {
      method: "PUT",
      body: blob,
      signal,
      headers: { ...target.headers, ...authorizationHeaders() },
      cache: "no-store",
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { message?: string } | null;
      throw new ApiError(response.status, body?.message ?? `part ${number} failed`);
    }
  }

  /** Retries transient failures with backoff. Client errors (4xx) are final. */
  async function sendWithRetry(id: string, number: number, blob: Blob) {
    for (let attempt = 1; ; attempt++) {
      const controller = new AbortController();
      controllers.current.add(controller);
      try {
        await sendPart(id, number, blob, controller.signal);
        return;
      } catch (error) {
        if (isPausedOrCancelled(error, controller.signal)) throw error;
        const clientError = error instanceof ApiError && error.status >= 400 && error.status < 500;
        if (clientError || attempt >= MAX_ATTEMPTS) throw error;
        await new Promise((resolve) => setTimeout(resolve, 2 ** attempt * 500));
      } finally {
        controllers.current.delete(controller);
      }
    }
  }

  async function runParts(id: string, current: UploadStatus, source: File) {
    if (runningRef.current) return;
    runningRef.current = true;
    pausedRef.current = false;
    setPhase("uploading");
    setStatus(current);
    const done = new Set(current.completed_parts);
    setPartsDone(done.size);
    setBytesDone(current.completed_parts.reduce((sum, n) => sum + partBytes(current, n), 0));
    const queue = current.missing_parts.slice();
    try {
      const worker = async () => {
        while (!pausedRef.current && queue.length > 0) {
          const number = queue.shift()!;
          const start = (number - 1) * current.part_size;
          const blob = source.slice(start, start + partBytes(current, number));
          await sendWithRetry(id, number, blob);
          done.add(number);
          setPartsDone(done.size);
          setBytesDone((bytes) => bytes + blob.size);
        }
      };
      await Promise.all(Array.from({ length: CONCURRENCY }, worker));
      if (pausedRef.current) {
        setPhase("paused");
        setMessage("Paused. Finished parts are kept; resume to continue.");
        return;
      }
      if (done.size < current.part_count) {
        throw new Error("some parts did not upload; retry the remaining parts");
      }
      await finish(id, false);
    } catch (error) {
      if (pausedRef.current) {
        setPhase("paused");
        setMessage("Paused. Finished parts are kept; resume to continue.");
        return;
      }
      setPhase("error");
      setMessage(error instanceof Error ? error.message : "Upload failed");
    } finally {
      runningRef.current = false;
    }
  }

  async function finish(id: string, allowDuplicate: boolean) {
    setPhase("assembling");
    setMessage(null);
    try {
      const result = await postJson<UploadResult>(`/v1/uploads/${id}/complete`, {
        allow_duplicate: allowDuplicate,
      });
      writeStored(storageKeyRef.current ?? "", null);
      setActiveId(null);
      setPhase("done");
      setMessage(
        result.quarantined
          ? "The file was flagged by the malware check and quarantined. It cannot be downloaded."
          : "Uploaded as a draft.",
      );
      if (result.thumbnail_url) {
        apiBlob(result.thumbnail_url.replace("/api/v1", "/v1"))
          .then((blob) => setThumbnail(URL.createObjectURL(blob)))
          .catch(() => setThumbnail(null));
      }
      onComplete(result);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && /already exists/.test(error.message)) {
        setPhase("duplicate");
        setMessage(error.message);
        return;
      }
      if (error instanceof ApiError && error.status === 400) {
        setPhase("rejected");
        setMessage(error.message);
        writeStored(storageKeyRef.current ?? "", null);
        setActiveId(null);
        return;
      }
      setPhase("error");
      setMessage(error instanceof Error ? error.message : "Could not finish the upload");
    }
  }

  async function start() {
    if (!file || !title.trim()) return;
    fileRef.current = file;
    setMessage(null);
    setThumbnail(null);
    setPartsDone(0);
    setBytesDone(0);
    const key = fingerprint(file);
    storageKeyRef.current = key;
    try {
      let current: UploadStatus | null = null;
      const stored = readStored(key);
      if (stored) {
        try {
          current = await apiFetch<UploadStatus>(`/v1/uploads/${stored}`);
          if (current.status !== "uploading") current = null;
        } catch {
          current = null;
        }
      }
      if (!current) {
        current = await postJson<UploadStatus>("/v1/uploads", {
          title: title.trim(),
          filename: file.name,
          content_type: contentTypeFor(file),
          size_bytes: file.size,
        });
      }
      writeStored(key, current.id);
      setActiveId(current.id);
      await runParts(current.id, current, file);
    } catch (error) {
      setPhase("error");
      setMessage(error instanceof Error ? error.message : "Could not start the upload");
    }
  }

  function pause() {
    pausedRef.current = true;
    controllers.current.forEach((c) => c.abort());
  }

  async function resume() {
    const id = uploadIdRef.current;
    const source = fileRef.current;
    if (!id || !source) {
      setPhase("error");
      setMessage("Select the same file again to resume this upload.");
      return;
    }
    setMessage(null);
    try {
      const current = await apiFetch<UploadStatus>(`/v1/uploads/${id}`);
      await runParts(id, current, source);
    } catch (error) {
      setPhase("error");
      setMessage(error instanceof Error ? error.message : "Could not resume the upload");
    }
  }

  async function cancel() {
    pause();
    const id = uploadIdRef.current;
    if (id) await postJson(`/v1/uploads/${id}/abort`, {}).catch(() => undefined);
    writeStored(storageKeyRef.current ?? "", null);
    setActiveId(null);
    setStatus(null);
    setBytesDone(0);
    setPartsDone(0);
    setPhase("idle");
    setMessage("Upload cancelled.");
  }

  const total = file?.size ?? 0;
  const percent = total ? Math.min(100, Math.round((bytesDone / total) * 100)) : 0;
  const busy = phase === "uploading" || phase === "assembling";
  const canStart = phase === "idle" || phase === "done" || phase === "rejected";
  const inFlight = phase === "uploading" || phase === "paused" || phase === "error" || phase === "duplicate";

  return (
    <div className="grid gap-3 sm:max-w-lg">
      <label className="text-sm">
        Title
        <input
          required
          value={title}
          disabled={busy || disabled}
          onChange={(e) => setTitle(e.target.value)}
          className="mt-1 w-full rounded border border-[var(--border)] bg-transparent px-3 py-2"
        />
      </label>
      <label className="text-sm">
        Content file (document, media, HTML5, SCORM, xAPI, cmi5, or H5P)
        <input
          type="file"
          accept=".zip,.pdf,.docx,.pptx,.mp4,.mp3,.png,.jpg,.jpeg,.gif,.webp,.svg,.html,.htm,.h5p"
          disabled={busy || disabled}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setPhase("idle");
            setMessage(null);
          }}
          className="mt-1 block w-full text-sm"
        />
      </label>

      {status && (phase === "uploading" || phase === "paused" || phase === "error") && (
        <div aria-live="polite">
          <div className="h-2 w-full overflow-hidden rounded bg-[var(--border)]">
            <div className="h-2 bg-[var(--accent)]" style={{ width: `${percent}%` }} />
          </div>
          <p className="mt-1 text-xs">
            {percent}% · {partsDone} of {status.part_count} parts
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {canStart && (
          <button
            type="button"
            disabled={!file || !title.trim() || disabled}
            onClick={start}
            className="w-fit rounded bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            Upload draft
          </button>
        )}
        {phase === "uploading" && (
          <button type="button" onClick={pause} className="rounded border px-3 py-2 text-sm">
            Pause
          </button>
        )}
        {phase === "paused" && (
          <button type="button" onClick={resume} className="rounded border px-3 py-2 text-sm">
            Resume
          </button>
        )}
        {phase === "error" && uploadId && (
          <button type="button" onClick={resume} className="rounded border px-3 py-2 text-sm">
            Retry remaining parts
          </button>
        )}
        {phase === "duplicate" && uploadId && (
          <button
            type="button"
            onClick={() => finish(uploadId, true)}
            className="rounded border px-3 py-2 text-sm"
          >
            Store another copy anyway
          </button>
        )}
        {inFlight && uploadId && (
          <button type="button" onClick={cancel} className="rounded border px-3 py-2 text-sm">
            Cancel upload
          </button>
        )}
      </div>

      {message && (
        <p
          role={phase === "error" || phase === "rejected" ? "alert" : "status"}
          className="rounded border border-[var(--border)] p-3 text-sm"
        >
          {message}
        </p>
      )}
      {thumbnail && (
        // eslint-disable-next-line @next/next/no-img-element -- blob URL from an authenticated fetch
        <img src={thumbnail} alt="Package thumbnail" className="h-40 w-40 rounded border" />
      )}
    </div>
  );
}
