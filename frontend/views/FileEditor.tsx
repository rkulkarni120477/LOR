"use client";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { apiFetch, postJson, putJson } from "@/lib/api";
import { FilePreview } from "@/components/FilePreview";
type Detail = {
  id: string;
  title: string;
  revision: number;
  status: string;
  description: string;
  subject: string;
  language: string;
  license: string;
  keywords: string[];
};
export default function FileEditor() {
  const { id } = useParams();
  const navigate = useNavigate(),
    client = useQueryClient();
  const query = useQuery({
    queryKey: ["library-file", id],
    queryFn: () => apiFetch<Detail>(`/v1/library/${id}`),
  });
  const [draft, setDraft] = useState<Detail | null>(null),
    [file, setFile] = useState<File | null>(null);
  const value = draft || query.data;
  const mutate = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: async () => {
      setDraft(null);
      setFile(null);
      await client.invalidateQueries();
    },
  });
  if (!value)
    return <Typography>{query.error?.message || "Loading file…"}</Typography>;
  const editable = ["draft", "rejected"].includes(value.status);
  return (
    <Stack spacing={3}>
      <Typography component="h1" variant="h4">
        Edit file content
      </Typography>
      {mutate.error && <Alert severity="error">{mutate.error.message}</Alert>}
      {mutate.isSuccess && <Alert severity="success">Saved.</Alert>}
      {!editable && (
        <Alert severity="info">
          Reviewed and published records are protected.{" "}
          <Button
            onClick={() =>
              mutate.mutate(async () => {
                const copy = await postJson<{ id: string }>(
                  `/v1/library/${id}/duplicate`,
                  {},
                );
                navigate(`/library/${copy.id}/file`);
              })
            }
          >
            Create editable copy
          </Button>
        </Alert>
      )}
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            {(
              [
                "title",
                "description",
                "subject",
                "language",
                "license",
              ] as const
            ).map((key) => (
              <TextField
                key={key}
                label={key}
                disabled={!editable}
                value={value[key] || ""}
                onChange={(e) => setDraft({ ...value, [key]: e.target.value })}
              />
            ))}
            <TextField
              label="Keywords / tags"
              disabled={!editable}
              value={(value.keywords || []).join(", ")}
              onChange={(e) =>
                setDraft({ ...value, keywords: e.target.value.split(",") })
              }
            />
            <Button
              disabled={!editable || mutate.isPending}
              onClick={() =>
                mutate.mutate(() =>
                  putJson(`/v1/library/${id}/metadata`, {
                    revision: value.revision,
                    title: value.title,
                    description: value.description,
                    subject: value.subject,
                    language: value.language,
                    license: value.license,
                    keywords: value.keywords,
                  }),
                )
              }
            >
              Save metadata
            </Button>
            <Typography component="h2" variant="h6">
              Replace file
            </Typography>
            <input
              type="file"
              aria-label="Replacement file"
              disabled={!editable}
              accept=".pdf,.docx,.pptx,.mp4,.mp3,.png,.jpg,.jpeg,.gif,.webp,.svg,.html,.htm,.zip,.h5p"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <Typography variant="body2">
              The replacement is scanned and validated before a new immutable
              file version is attached. Existing file versions are retained.
            </Typography>
            <Button
              disabled={!editable || !file || mutate.isPending}
              variant="contained"
              onClick={() =>
                mutate.mutate(async () => {
                  const form = new FormData();
                  form.append("file", file!);
                  form.append("revision", String(value.revision));
                  return apiFetch(`/v1/library/${id}/file`, {
                    method: "POST",
                    body: form,
                  });
                })
              }
            >
              Upload replacement version
            </Button>
          </Stack>
        </CardContent>
      </Card>
      <FilePreview key={`${id}-${value.revision}`} id={id!} />
    </Stack>
  );
}
