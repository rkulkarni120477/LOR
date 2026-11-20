"use client";

import { useState } from "react";
import { Alert, Box, Button, Chip, Divider, Stack, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { apiBlob, apiFetch } from "@/lib/api";

export type Preview = {
  id: string;
  title: string;
  kind: "file" | "rich_text" | "quiz" | "assessment";
  revision: number;
  html?: string;
  passing_score?: number;
  total_points?: number;
  answers_visible?: boolean;
  questions?: {
    prompt: string;
    type: "single_choice" | "true_false";
    options: string[];
    points: number;
    correct?: number;
    explanation?: string;
  }[];
  content_type?: string | null;
  original_filename?: string | null;
  size_bytes?: number | null;
  previewable?: boolean;
  pdf?: boolean;
};

export function useItemPreview(id: string | null) {
  return useQuery({
    queryKey: ["library-preview", id],
    queryFn: () => apiFetch<Preview>(`/v1/library/${id}/preview`),
    enabled: !!id,
  });
}

/** Downloads go out as attachments, so PDFs open from an authenticated blob in a new tab. */
function OpenPdfButton({ id }: { id: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Stack spacing={1} sx={{ alignItems: "flex-start" }}>
      <Button
        variant="outlined"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            const blob = await apiBlob(`/v1/content/${id}/download`);
            const url = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
            window.open(url, "_blank", "noopener");
            window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Could not open the PDF");
          } finally {
            setBusy(false);
          }
        }}
      >
        Open PDF
      </Button>
      {error && <Alert severity="error">{error}</Alert>}
    </Stack>
  );
}

/** Renders a preview by format. Rich text HTML is sanitized by the server before it arrives. */
export function LibraryPreview({ item }: { item: Preview }) {
  if (item.kind === "rich_text") {
    return (
      <Box
        data-testid="rich-text-preview"
        sx={{ "& h1": { fontSize: "1.6rem" }, "& h2": { fontSize: "1.3rem" }, "& pre": { bgcolor: "#f1f4f9", p: 1, overflow: "auto" } }}
        dangerouslySetInnerHTML={{ __html: item.html ?? "" }}
      />
    );
  }
  if (item.kind === "quiz" || item.kind === "assessment") {
    return (
      <Stack spacing={2}>
        <Typography variant="body2" color="text.secondary">
          {item.kind === "assessment" ? "Assessment" : "Quiz"} · {item.total_points} points · pass mark{" "}
          {item.passing_score}%
        </Typography>
        {!item.answers_visible && (
          <Alert severity="info">Answer key is shown to the content owner and managers only.</Alert>
        )}
        {(item.questions ?? []).map((q, index) => (
          <Box key={index}>
            <Typography sx={{ fontWeight: 600 }}>
              {index + 1}. {q.prompt} <Chip size="small" label={`${q.points} pt`} sx={{ ml: 1 }} />
            </Typography>
            <Box component="ol" sx={{ pl: 3, m: 0 }}>
              {q.options.map((option, optionIndex) => (
                <li key={optionIndex} style={{ fontWeight: q.correct === optionIndex ? 700 : 400 }}>
                  {option}
                  {q.correct === optionIndex && " ✓"}
                </li>
              ))}
            </Box>
            {q.explanation && (
              <Typography variant="body2" color="text.secondary">
                Explanation: {q.explanation}
              </Typography>
            )}
            <Divider sx={{ mt: 1 }} />
          </Box>
        ))}
      </Stack>
    );
  }
  return (
    <Stack spacing={1}>
      <Typography>File: {item.original_filename ?? "no file yet"}</Typography>
      <Typography variant="body2" color="text.secondary">
        {item.content_type ?? "unknown type"}
        {item.size_bytes ? ` · ${Math.round(item.size_bytes / 1024)} KB` : ""}
      </Typography>
      {item.pdf && <OpenPdfButton id={item.id} />}
      {item.previewable && (
        <Typography variant="body2">Package contents are available on the object detail page.</Typography>
      )}
    </Stack>
  );
}
