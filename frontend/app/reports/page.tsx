"use client";

import { useEffect, useState } from "react";

import { AgentStream } from "@/components/AgentStream";
import { ApiError, apiFetch } from "@/lib/api";

type Completions = {
  total_completions: number;
  unique_learners: number;
  by_object: { object_id: string; completions: number }[];
};

export default function ReportsPage() {
  const [summary, setSummary] = useState<Completions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<Completions>("/v1/reports/completions")
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load report");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Reports</h1>

      <section className="space-y-3">
        <h2 className="font-medium">Completion summary</h2>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {summary && (
          <>
            <div className="flex gap-6 text-sm">
              <p>
                <span className="text-2xl font-semibold">{summary.total_completions}</span>{" "}
                completions
              </p>
              <p>
                <span className="text-2xl font-semibold">{summary.unique_learners}</span> learners
              </p>
            </div>
            <table className="w-full text-left text-sm">
              <thead className="text-[var(--muted)]">
                <tr>
                  <th className="py-1">Learning object</th>
                  <th className="py-1 text-right">Completions</th>
                </tr>
              </thead>
              <tbody>
                {summary.by_object.map((row) => (
                  <tr key={row.object_id} className="border-t border-[var(--border)]">
                    <td className="py-1 break-all">{row.object_id}</td>
                    <td className="py-1 text-right">{row.completions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="font-medium">Ask a question</h2>
        <p className="text-sm text-[var(--muted)]">
          Try: &quot;How many completions do we have?&quot; or &quot;Completions by object&quot;.
        </p>
        <AgentStream
          endpoint="/v1/agents/ask"
          buildBody={(question) => ({ question })}
          placeholder="Ask about completions"
        />
      </section>
    </div>
  );
}
