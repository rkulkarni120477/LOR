"use client";

import { useState } from "react";

import { ApiError, apiFetch, putJson } from "@/lib/api";
import { ResumableUpload, type UploadResult } from "@/components/ResumableUpload";

type Created = { id: string; title: string; status: string };
type Meta = {
  title: string;
  description?: string | null;
  language?: string | null;
  keywords: string[];
  subject?: string | null;
  learning_resource_type?: string | null;
  license?: string | null;
  alt_text_provided?: boolean | null;
  captions_provided?: boolean | null;
};
type AgentRun = {
  status: string;
  compliance_score?: number | null;
  compliance_issues: string[];
  extracted_metadata?: Record<string, unknown> | null;
};

export default function ContributePage() {
  const [created, setCreated] = useState<Created | null>(null);
  const [meta, setMeta] = useState<Meta>({ title: "", keywords: [] });
  const [keywords, setKeywords] = useState("");
  const [agent, setAgent] = useState<AgentRun | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function fail(err: unknown) {
    setMessage(err instanceof ApiError ? err.message : "Something went wrong");
  }

  function handleUploaded(result: UploadResult) {
    setCreated({ id: result.id, title: result.title, status: result.status });
    setMeta((m) => ({ ...m, title: result.title }));
    setMessage(
      result.quarantined
        ? "The package was quarantined by the malware check and cannot be used."
        : "Uploaded as draft.",
    );
  }

  async function saveMetadata(event: React.FormEvent) {
    event.preventDefault();
    if (!created) return;
    setBusy(true);
    try {
      const payload: Meta = {
        ...meta,
        keywords: keywords
          .split(",")
          .map((k) => k.trim())
          .filter(Boolean),
      };
      await putJson(`/v1/metadata/${created.id}`, payload);
      setMessage("Metadata saved.");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function runAiDraft() {
    if (!created) return;
    setBusy(true);
    try {
      const result = await apiFetch<AgentRun>(`/v1/agents/ingest/${created.id}`, {
        method: "POST",
      });
      setAgent(result);
      setMessage(
        result.status === "paused"
          ? "The AI check found issues and paused for review. Fix them, then submit."
          : "AI draft complete. Empty fields were filled in.",
      );
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!created) return;
    setBusy(true);
    try {
      const result = await apiFetch<{ status: string }>(`/v1/workflow/${created.id}/submit`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setCreated({ ...created, status: result.status });
      setMessage(`Submitted for review (status: ${result.status}).`);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Contribute</h1>
      {message && <p className="rounded border border-[var(--border)] p-3 text-sm">{message}</p>}

      <section>
        <h2 className="mb-3 font-medium">1. Upload a package</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Large packages upload in parts. You can pause and resume, and a failed part is retried.
        </p>
        <ResumableUpload onComplete={handleUploaded} disabled={!!created} />
      </section>

      {created && (
        <>
          <section>
            <h2 className="mb-3 font-medium">2. Metadata</h2>
            <form onSubmit={saveMetadata} className="grid gap-3 sm:max-w-2xl">
              <Field label="Title" value={meta.title} onChange={(v) => setMeta({ ...meta, title: v })} />
              <Field
                label="Description"
                value={meta.description ?? ""}
                onChange={(v) => setMeta({ ...meta, description: v })}
                multiline
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Language (e.g. en)" value={meta.language ?? ""} onChange={(v) => setMeta({ ...meta, language: v })} />
                <Field label="Subject" value={meta.subject ?? ""} onChange={(v) => setMeta({ ...meta, subject: v })} />
                <Field label="Format (e.g. course)" value={meta.learning_resource_type ?? ""} onChange={(v) => setMeta({ ...meta, learning_resource_type: v })} />
                <Field label="License (e.g. CC-BY-4.0)" value={meta.license ?? ""} onChange={(v) => setMeta({ ...meta, license: v })} />
              </div>
              <Field label="Keywords (comma separated)" value={keywords} onChange={setKeywords} />
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!meta.alt_text_provided}
                  onChange={(e) => setMeta({ ...meta, alt_text_provided: e.target.checked })}
                />
                All images have alt text
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!meta.captions_provided}
                  onChange={(e) => setMeta({ ...meta, captions_provided: e.target.checked })}
                />
                Video has captions
              </label>
              <div className="flex flex-wrap gap-2">
                <button disabled={busy} className="rounded border border-[var(--border)] px-4 py-2 text-sm">
                  Save metadata
                </button>
                <button type="button" disabled={busy} onClick={runAiDraft} className="rounded border border-[var(--border)] px-4 py-2 text-sm">
                  Run AI draft and check
                </button>
                <button type="button" disabled={busy} onClick={submit} className="rounded bg-[var(--accent)] px-4 py-2 text-sm text-white">
                  Submit for review
                </button>
              </div>
            </form>
          </section>

          {agent && (
            <section className="space-y-2 text-sm">
              <h2 className="font-medium">AI check</h2>
              <p>Compliance score: {agent.compliance_score ?? "n/a"}</p>
              {agent.compliance_issues.length > 0 && (
                <ul className="list-disc pl-5 text-red-600">
                  {agent.compliance_issues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  multiline,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
}) {
  const className = "mt-1 w-full rounded border border-[var(--border)] bg-transparent px-3 py-2";
  return (
    <label className="text-sm">
      {label}
      {multiline ? (
        <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={3} className={className} />
      ) : (
        <input value={value} onChange={(e) => onChange(e.target.value)} className={className} />
      )}
    </label>
  );
}
