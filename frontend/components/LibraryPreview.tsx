"use client";

import { Alert, Box, Chip, Divider, Stack, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { FilePreview } from "@/components/FilePreview";
import { AssessmentPlayer } from "@/components/AssessmentPlayer";

export type Preview = {
  id: string;
  title: string;
  kind: "file" | "rich_text" | "quiz" | "assessment";
  revision: number;
  status?: string;
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

/** Renders a preview by format. Rich text HTML is sanitized by the server before it arrives. */
export function LibraryPreview({ item }: { item: Preview }) {
  if (item.kind === "rich_text") {
    return (
      <Box
        data-testid="rich-text-preview"
        sx={{
          "& h1": { fontSize: "1.6rem" },
          "& h2": { fontSize: "1.3rem" },
          "& pre": { bgcolor: "#f1f4f9", p: 1, overflow: "auto" },
        }}
        dangerouslySetInnerHTML={{ __html: item.html ?? "" }}
      />
    );
  }
  if (item.kind === "quiz" || item.kind === "assessment") {
    return (
      <Stack spacing={2}>
        <Typography variant="body2" color="text.secondary">
          {item.kind === "assessment" ? "Assessment" : "Quiz"} ·{" "}
          {item.total_points} points · pass mark {item.passing_score}%
        </Typography>
        {item.status === "published" && !item.answers_visible && (
          <AssessmentPlayer item={item} />
        )}
        {!item.answers_visible && (
          <Alert severity="info">
            Answer key is shown to the content owner and managers only.
          </Alert>
        )}
        {(item.questions ?? []).map((q, index) => (
          <Box key={index}>
            <Typography sx={{ fontWeight: 600 }}>
              {index + 1}. {q.prompt}{" "}
              <Chip size="small" label={`${q.points} pt`} sx={{ ml: 1 }} />
            </Typography>
            <Box component="ol" sx={{ pl: 3, m: 0 }}>
              {q.options.map((option, optionIndex) => (
                <li
                  key={optionIndex}
                  style={{ fontWeight: q.correct === optionIndex ? 700 : 400 }}
                >
                  {option}
                  {q.correct === optionIndex && (
                    <span aria-label="Correct answer"> ✓</span>
                  )}
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
  return <FilePreview id={item.id} />;
}
