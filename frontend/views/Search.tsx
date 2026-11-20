"use client";

import { Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import Link from "@/components/Link";

import { apiFetch } from "@/lib/api";

type Hit = {
  id: string;
  title: string;
  description: string | null;
  subject: string | null;
  learning_resource_type: string | null;
  keywords: string[];
};
type Facet = { value: string; count: number };
type SearchResponse = {
  items: Hit[];
  total: number;
  page: number;
  page_size: number;
  facets: { subject: Facet[]; format: Facet[] };
};

export default function SearchPage() {
  return (
    <Suspense
      fallback={
        <p className="text-sm text-[var(--muted)]">Loading search...</p>
      }
    >
      <SearchContent />
    </Suspense>
  );
}

function SearchContent() {
  const [searchParams] = useSearchParams();
  const [q, setQ] = useState(() => searchParams.get("q") ?? "");
  const [subject, setSubject] = useState(
    () => searchParams.get("subject") ?? "",
  );
  const [format, setFormat] = useState("");
  const result = useQuery({
    queryKey: ["search", q, subject, format],
    queryFn: () => {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (subject) params.set("subject", subject);
      if (format) params.set("format", format);
      return apiFetch<SearchResponse>(`/v1/search?${params.toString()}`);
    },
  });
  const data = result.data;
  const error = result.error?.message;

  return (
    <div className="grid gap-6 md:grid-cols-[14rem_1fr]">
      <aside className="space-y-5 text-sm">
        <FacetGroup
          title="Subject"
          facets={data?.facets.subject ?? []}
          selected={subject}
          onSelect={setSubject}
        />
        <FacetGroup
          title="Format"
          facets={data?.facets.format ?? []}
          selected={format}
          onSelect={setFormat}
        />
      </aside>

      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">Search</h1>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search titles, descriptions, keywords"
          aria-label="Search learning objects"
          className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2"
        />
        {!data && !error && (
          <p className="text-sm text-[var(--muted)]">Searching...</p>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {data && (
          <p className="text-sm text-[var(--muted)]">
            {data.total} result{data.total === 1 ? "" : "s"}
          </p>
        )}
        <ul className="space-y-3">
          {data?.items.map((hit) => (
            <li
              key={hit.id}
              className="rounded border border-[var(--border)] p-4"
            >
              <h2 className="font-medium">
                <Link
                  className="text-blue-700 underline"
                  href={`/objects?id=${encodeURIComponent(hit.id)}`}
                >
                  {hit.title}
                </Link>
              </h2>
              {hit.description && (
                <p className="mt-1 text-sm text-[var(--muted)]">
                  {hit.description}
                </p>
              )}
              <p className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
                {hit.subject && <span>Subject: {hit.subject}</span>}
                {hit.learning_resource_type && (
                  <span>Format: {hit.learning_resource_type}</span>
                )}
                {hit.keywords.map((k) => (
                  <span
                    key={k}
                    className="rounded bg-[var(--border)] px-2 py-0.5"
                  >
                    {k}
                  </span>
                ))}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function FacetGroup({
  title,
  facets,
  selected,
  onSelect,
}: {
  title: string;
  facets: Facet[];
  selected: string;
  onSelect: (value: string) => void;
}) {
  return (
    <div>
      <h2 className="mb-2 font-medium">{title}</h2>
      <ul className="space-y-1">
        {selected && (
          <li>
            <button className="underline" onClick={() => onSelect("")}>
              Clear {title.toLowerCase()}
            </button>
          </li>
        )}
        {facets.map((f) => (
          <li key={f.value}>
            <button
              onClick={() => onSelect(f.value)}
              aria-pressed={selected === f.value}
              className={
                selected === f.value ? "font-semibold" : "text-[var(--muted)]"
              }
            >
              {f.value} ({f.count})
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
