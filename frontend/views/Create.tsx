"use client";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Stack,
  Typography,
} from "@mui/material";
import { useNavigate } from "react-router-dom";
import { apiFetch, postJson } from "@/lib/api";
import { can, loadSession } from "@/lib/auth";

export default function Create() {
  const navigate = useNavigate();
  const allowed = can(loadSession(), "content.create");
  const templates = useQuery({
    queryKey: ["library", "templates"],
    queryFn: () =>
      apiFetch<{ items: { id: string; title: string; kind: string }[] }>(
        "/v1/library?template=true&page_size=100",
      ),
    enabled: allowed,
  });
  const catalog = useQuery({
    queryKey: ["template-catalog"],
    queryFn: () =>
      apiFetch<{ items: { key: string; title: string; kind: string }[] }>(
        "/v1/library/templates/catalog",
      ),
    enabled: allowed,
  });
  const builtin = useMutation({
    mutationFn: (key: string) =>
      postJson<{ id: string }>(`/v1/library/templates/${key}`, {}),
    onSuccess: (item) => navigate(`/library/${item.id}/edit`),
  });
  const duplicate = useMutation({
    mutationFn: (id: string) =>
      postJson<{ id: string }>(`/v1/library/${id}/duplicate`, {}),
    onSuccess: (item) => navigate(`/library/${item.id}/edit`),
  });
  if (!allowed)
    return (
      <Alert severity="warning">Content creation permission is required.</Alert>
    );
  return (
    <Stack spacing={3}>
      <Typography variant="h4" component="h1">
        Create learning content
      </Typography>
      <Typography>
        Start a document, quiz, or assessment. Drafts save automatically as you
        work.
      </Typography>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        {[
          [
            "rich_text",
            "Document",
            "Write and format content or edit HTML source.",
          ],
          ["quiz", "Quiz", "Build questions with feedback and scoring."],
          [
            "assessment",
            "Assessment",
            "Create a graded assessment with a passing score.",
          ],
        ].map(([kind, title, description]) => (
          <Card variant="outlined" key={kind} sx={{ flex: 1 }}>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">{title}</Typography>
                <Typography>{description}</Typography>
                <Button
                  variant="contained"
                  component={Link}
                  to={`/library/new/${kind}`}
                >
                  Create {title.toLowerCase()}
                </Button>
              </Stack>
            </CardContent>
          </Card>
        ))}
      </Stack>
      <Typography component="h2" variant="h5">
        Start from a template
      </Typography>
      {builtin.error && <Alert severity="error">{builtin.error.message}</Alert>}
      {catalog.data?.items.map((t) => (
        <Card variant="outlined" key={t.key}>
          <CardContent>
            <Typography>{t.title}</Typography>
            <Button
              disabled={builtin.isPending}
              onClick={() => builtin.mutate(t.key)}
            >
              Use {t.title.toLowerCase()}
            </Button>
          </CardContent>
        </Card>
      ))}
      {templates.isLoading && (
        <Typography role="status">Loading templates…</Typography>
      )}
      {(templates.error || duplicate.error) && (
        <Alert severity="error">
          {(templates.error || duplicate.error)?.message}
        </Alert>
      )}
      {!templates.isLoading && !templates.data?.items.length && (
        <Typography>
          No shared templates yet. Save any authored document, quiz, or
          assessment as a template to reuse it here.
        </Typography>
      )}
      {templates.data?.items
        .filter((t) => t.kind !== "file")
        .map((t) => (
          <Card variant="outlined" key={t.id}>
            <CardContent>
              <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
                <Typography>{t.title}</Typography>
                <Button
                  disabled={duplicate.isPending}
                  onClick={() => duplicate.mutate(t.id)}
                >
                  Use template
                </Button>
              </Stack>
            </CardContent>
          </Card>
        ))}
      <Button component={Link} to="/contribute">
        Upload existing content
      </Button>
    </Stack>
  );
}
