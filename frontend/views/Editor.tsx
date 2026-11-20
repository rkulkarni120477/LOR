"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Checkbox,
  FormControlLabel,
  IconButton,
  MenuItem,
  Paper,
  Radio,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { apiFetch, postJson, putJson } from "@/lib/api";
import { LibraryPreview, useItemPreview } from "@/components/LibraryPreview";
import { AiAssistPanel } from "@/components/AiAssistPanel";
import DOMPurify from "dompurify";
import { loadSession } from "@/lib/auth";

type Kind = "rich_text" | "quiz" | "assessment";
type QuestionDraft = {
  prompt: string;
  type: "single_choice" | "true_false";
  options: string[];
  correct: number;
  points: number;
  explanation: string;
};
type Form = {
  title: string;
  description: string;
  subject: string;
  resourceType: string;
  keywords: string;
  html: string;
  passingScore: number;
  isTemplate: boolean;
  questions: QuestionDraft[];
  language: string;
  license: string;
  difficulty: string;
  durationMinutes: string;
  learningStandard: string;
};
type Detail = {
  id: string;
  status?: string;
  title: string;
  kind: string;
  revision: number;
  is_template: boolean;
  description: string;
  subject: string | null;
  learning_resource_type: string | null;
  keywords: string[];
  body: { html?: string; passing_score?: number; questions?: QuestionDraft[] };
  language?: string;
  license?: string;
  difficulty?: string;
  duration_minutes?: number;
  learning_standard?: string;
};
const TOOLBAR: [string, string, string?][] = [
  ["B", "bold"],
  ["I", "italic"],
  ["U", "underline"],
  ["Heading", "formatBlock", "H2"],
  ["Subheading", "formatBlock", "H3"],
  ["Bullets", "insertUnorderedList"],
  ["Numbered", "insertOrderedList"],
  ["Quote", "formatBlock", "BLOCKQUOTE"],
  ["Code", "formatBlock", "PRE"],
  ["Link", "createLink"],
  ["Clear format", "removeFormat"],
];

type SaveStatus = "idle" | "saving" | "saved" | "error" | "conflict";

const NEW_QUESTION: QuestionDraft = {
  prompt: "",
  type: "single_choice",
  options: ["", ""],
  correct: 0,
  points: 1,
  explanation: "",
};

function emptyForm(): Form {
  return {
    title: "",
    description: "",
    subject: "",
    resourceType: "",
    keywords: "",
    html: "",
    passingScore: 70,
    isTemplate: false,
    questions: [],
    language: "en",
    license: "",
    difficulty: "beginner",
    durationMinutes: "",
    learningStandard: "",
  };
}

function fromDetail(d: Detail): Form {
  return {
    title: d.title,
    description: d.description ?? "",
    subject: d.subject ?? "",
    resourceType: d.learning_resource_type ?? "",
    keywords: (d.keywords ?? []).join(", "),
    html: d.body?.html ?? "",
    passingScore: d.body?.passing_score ?? 70,
    isTemplate: d.is_template,
    questions: (d.body?.questions ?? []).map((q) => ({
      prompt: q.prompt,
      type: q.type,
      options: [...q.options],
      correct: q.correct,
      points: q.points,
      explanation: q.explanation ?? "",
    })),
    language: d.language || "en",
    license: d.license || "",
    difficulty: d.difficulty || "beginner",
    durationMinutes: d.duration_minutes?.toString() || "",
    learningStandard: d.learning_standard || "",
  };
}

function metadataOf(form: Form) {
  return {
    title: form.title.trim(),
    description: form.description,
    subject: form.subject.trim(),
    learning_resource_type: form.resourceType.trim(),
    keywords: form.keywords
      .split(",")
      .map((k) => k.trim())
      .filter(Boolean),
    is_template: form.isTemplate,
    language: form.language.trim() || null,
    license: form.license.trim() || null,
    difficulty: form.difficulty || null,
    duration_minutes: form.durationMinutes
      ? Number(form.durationMinutes)
      : null,
    learning_standard: form.learningStandard || null,
  };
}

/** The payload sent on save. Serialized and compared to decide whether anything changed. */
function payloadOf(kind: Kind, form: Form) {
  if (kind === "rich_text") return { ...metadataOf(form), html: form.html };
  return {
    ...metadataOf(form),
    passing_score: form.passingScore,
    questions: form.questions.map((q) => ({
      prompt: q.prompt,
      type: q.type,
      options: q.type === "true_false" ? ["True", "False"] : q.options,
      correct: q.correct,
      points: q.points,
      explanation: q.explanation,
    })),
  };
}

function readBackup(key: string, kind: Kind, server: Form): Form | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const stored = JSON.parse(raw) as Form;
    return JSON.stringify(payloadOf(kind, stored)) ===
      JSON.stringify(payloadOf(kind, server))
      ? null
      : stored;
  } catch {
    // Storage can be blocked or hold malformed data. The editor works without it.
    return null;
  }
}

export default function Editor() {
  const navigate = useNavigate();
  const [copyError, setCopyError] = useState<string | null>(null);
  const params = useParams<{ id?: string; kind?: string }>();
  const id = params.id ?? null;
  const newKind = (params.kind as Kind) || "rich_text";
  const detail = useQuery({
    queryKey: ["library-item", id],
    queryFn: () => apiFetch<Detail>(`/v1/library/${id}`),
    enabled: !!id,
  });

  if (id && detail.error)
    return <Alert severity="error">{detail.error.message}</Alert>;
  if (id && !detail.data) return <Typography>Loading…</Typography>;

  const kind: Kind = (detail.data?.kind as Kind) ?? newKind;
  if (
    detail.data?.status &&
    !["draft", "rejected"].includes(detail.data.status)
  )
    return (
      <Stack spacing={2}>
        <Alert severity="info">
          This content is {detail.data.status}. Create an editable copy to
          preserve its reviewed version.
        </Alert>
        {copyError && <Alert severity="error">{copyError}</Alert>}
        <Button
          onClick={async () => {
            try {
              const copy = await postJson<{ id: string }>(
                `/v1/library/${id}/duplicate`,
                {},
              );
              navigate(`/library/${copy.id}/edit`);
            } catch (reason) {
              setCopyError(
                reason instanceof Error
                  ? reason.message
                  : "Could not create a copy",
              );
            }
          }}
        >
          Create editable copy
        </Button>
      </Stack>
    );
  return (
    <EditorBody
      key={id ?? `new-${newKind}`}
      id={id}
      kind={kind}
      initialForm={detail.data ? fromDetail(detail.data) : emptyForm()}
      initialRevision={detail.data?.revision ?? 1}
    />
  );
}

function EditorBody({
  id,
  kind,
  initialForm,
  initialRevision,
}: {
  id: string | null;
  kind: Kind;
  initialForm: Form;
  initialRevision: number;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const subject = loadSession()?.subject || "anonymous";
  const storageKey = `lor.library.draft.${subject}.${id ?? `new-${kind}`}`;

  const [form, setForm] = useState<Form>(initialForm);
  const [revision, setRevision] = useState(initialRevision);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restorable, setRestorable] = useState<Form | null>(() =>
    readBackup(storageKey, kind, initialForm),
  );
  const [showPreview, setShowPreview] = useState(false);
  const [sourceMode, setSourceMode] = useState(false);
  const currentForm = useRef(form);
  currentForm.current = form;
  const lastSaved = useRef(
    id ? JSON.stringify(payloadOf(kind, initialForm)) : "",
  );
  const saving = useRef(false);
  const editorRef = useRef<HTMLDivElement>(null);
  const preview = useItemPreview(showPreview ? id : null);
  const isRich = kind === "rich_text";

  // Keep a per-browser backup of unsent edits, so a closed tab does not lose text.
  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(form));
    } catch {
      // Ignore quota and privacy-mode errors.
    }
  }, [form, storageKey]);

  // Autosave: one save per pause in typing, with optimistic concurrency on the revision.
  useEffect(() => {
    const serialized = JSON.stringify(payloadOf(kind, form));
    if (serialized === lastSaved.current || saving.current) return;
    if (!form.title.trim()) return;
    const timer = window.setTimeout(async () => {
      saving.current = true;
      setStatus("saving");
      setError(null);
      try {
        const payload = JSON.parse(serialized) as Record<string, unknown>;
        if (!id) {
          const created = await postJson<Detail>(
            isRich ? "/v1/library/rich-text" : "/v1/library/quizzes",
            isRich ? payload : { ...payload, kind },
          );
          lastSaved.current = serialized;
          if (
            JSON.stringify(payloadOf(kind, currentForm.current)) !== serialized
          ) {
            window.localStorage.setItem(
              `lor.library.draft.${subject}.${created.id}`,
              JSON.stringify(currentForm.current),
            );
          }
          window.localStorage.removeItem(storageKey);
          void queryClient.invalidateQueries({ queryKey: ["library"] });
          navigate(`/library/${created.id}/edit`, { replace: true });
          return;
        }
        const result = await putJson<{ revision: number; saved_at: string }>(
          `/v1/library/${id}/draft`,
          { ...payload, revision },
        );
        lastSaved.current = serialized;
        setRevision(result.revision);
        setSavedAt(result.saved_at);
        setStatus("saved");
        void queryClient.invalidateQueries({ queryKey: ["library"] });
      } catch (err) {
        const code = (err as { status?: number }).status;
        if (code === 409) {
          setStatus("conflict");
          setError(
            "This item was changed in another session. Reload to get the latest version; your unsent edits are kept in this browser.",
          );
        } else {
          setStatus("error");
          setError(err instanceof Error ? err.message : "Save failed");
        }
      } finally {
        saving.current = false;
      }
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [form, revision, id, kind, isRich, navigate, queryClient]);

  useEffect(() => {
    if (!sourceMode && editorRef.current)
      editorRef.current.innerHTML = DOMPurify.sanitize(
        currentForm.current.html,
      );
  }, [sourceMode]);

  // Warn before leaving while a save is pending or has failed.
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (status === "saving" || status === "error") event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [status]);

  function update<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateQuestion(index: number, patch: Partial<QuestionDraft>) {
    setForm((current) => ({
      ...current,
      questions: current.questions.map((q, i) =>
        i === index ? { ...q, ...patch } : q,
      ),
    }));
  }

  function applyCommand(command: string, value?: string) {
    if (command === "createLink") {
      const url = window.prompt("Link address (https:// or mailto:)");
      if (!url) return;
      document.execCommand("createLink", false, url);
    } else {
      document.execCommand(command, false, value);
    }
    editorRef.current?.focus();
    update("html", editorRef.current?.innerHTML ?? "");
  }

  const statusText = useMemo(() => {
    switch (status) {
      case "saving":
        return "Saving…";
      case "saved":
        return savedAt
          ? `All changes saved at ${new Date(savedAt).toLocaleTimeString()}`
          : "All changes saved";
      case "error":
        return "Not saved yet. Will retry after your next change.";
      case "conflict":
        return "Changed in another session";
      default:
        return form.title.trim() ? "" : "Add a title to start saving.";
    }
  }, [status, savedAt, form.title]);

  return (
    <Stack spacing={2} sx={{ maxWidth: 980 }}>
      <Stack
        sx={{
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 1,
        }}
        direction="row"
      >
        <Button component={RouterLink} to="/library">
          ← Back to library
        </Button>
        <Typography
          variant="body2"
          role="status"
          aria-live="polite"
          color={
            status === "error" || status === "conflict"
              ? "error"
              : "text.secondary"
          }
        >
          {statusText}
        </Typography>
      </Stack>

      {restorable && (
        <Alert
          severity="warning"
          action={
            <Stack sx={{ gap: 1 }} direction="row">
              <Button
                color="inherit"
                size="small"
                onClick={() => {
                  setForm(restorable);
                  if (editorRef.current)
                    editorRef.current.innerHTML = DOMPurify.sanitize(
                      restorable.html,
                    );
                  setRestorable(null);
                }}
              >
                Restore
              </Button>
              <Button
                color="inherit"
                size="small"
                onClick={() => {
                  window.localStorage.removeItem(storageKey);
                  setRestorable(null);
                }}
              >
                Discard
              </Button>
            </Stack>
          }
        >
          Unsent changes from this browser were found for this item.
        </Alert>
      )}
      {error && (
        <Alert
          severity={status === "conflict" ? "error" : "warning"}
          action={
            status === "conflict" ? (
              <Button
                color="inherit"
                size="small"
                onClick={() => window.location.reload()}
              >
                Reload
              </Button>
            ) : undefined
          }
        >
          {error}
        </Alert>
      )}

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            {id ? "Edit" : "New"}{" "}
            {isRich ? "rich text" : kind === "quiz" ? "quiz" : "assessment"}
          </Typography>
          <TextField
            label="Title"
            value={form.title}
            onChange={(e) => update("title", e.target.value)}
            slotProps={{ htmlInput: { maxLength: 500 } }}
            required
          />
          <TextField
            label="Description"
            value={form.description}
            onChange={(e) => update("description", e.target.value)}
            multiline
            minRows={2}
            slotProps={{ htmlInput: { maxLength: 5000 } }}
          />
          <Stack sx={{ gap: 2 }} direction={{ xs: "column", sm: "row" }}>
            <TextField
              label="Subject"
              value={form.subject}
              onChange={(e) => update("subject", e.target.value)}
              fullWidth
            />
            <TextField
              label="Resource type"
              value={form.resourceType}
              onChange={(e) => update("resourceType", e.target.value)}
              fullWidth
            />
          </Stack>
          <TextField
            label="Keywords (comma separated)"
            value={form.keywords}
            onChange={(e) => update("keywords", e.target.value)}
          />
          <Stack spacing={2} direction={{ xs: "column", md: "row" }}>
            <TextField
              label="Language"
              value={form.language}
              onChange={(e) => update("language", e.target.value)}
            />
            <TextField
              label="License"
              value={form.license}
              onChange={(e) => update("license", e.target.value)}
            />
            <TextField
              label="Duration (minutes)"
              type="number"
              value={form.durationMinutes}
              onChange={(e) => update("durationMinutes", e.target.value)}
            />
            <TextField
              select
              label="Difficulty"
              value={form.difficulty}
              onChange={(e) => update("difficulty", e.target.value)}
            >
              {["beginner", "intermediate", "advanced"].map((v) => (
                <MenuItem key={v} value={v}>
                  {v}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Learning standard"
              value={form.learningStandard}
              onChange={(e) => update("learningStandard", e.target.value)}
            />
          </Stack>
          <FormControlLabel
            control={
              <Checkbox
                checked={form.isTemplate}
                onChange={(e) => update("isTemplate", e.target.checked)}
              />
            }
            label="Save as a template (others can duplicate it)"
          />
        </Stack>
      </Paper>

      {isRich ? (
        <Paper sx={{ p: 3 }}>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            <Button
              aria-pressed={!sourceMode}
              onClick={() => setSourceMode(false)}
            >
              Visual editor
            </Button>
            <Button
              aria-pressed={sourceMode}
              onClick={() => setSourceMode(true)}
            >
              HTML source
            </Button>
          </Stack>
          {sourceMode ? (
            <TextField
              label="HTML source"
              multiline
              minRows={16}
              fullWidth
              value={form.html}
              onChange={(e) => update("html", e.target.value)}
              helperText="Unsafe scripts and attributes are removed when saved and previewed."
            />
          ) : (
            <>
              <Stack
                direction="row"
                sx={{ gap: 1, flexWrap: "wrap", mb: 1 }}
                role="toolbar"
                aria-label="Formatting"
              >
                {TOOLBAR.map(([label, command, value]) => (
                  <Button
                    key={label}
                    size="small"
                    variant="outlined"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => applyCommand(command, value)}
                  >
                    {label}
                  </Button>
                ))}
              </Stack>
              <div
                ref={editorRef}
                contentEditable
                suppressContentEditableWarning
                role="textbox"
                aria-label="Content"
                aria-multiline="true"
                onInput={(e) =>
                  update("html", (e.target as HTMLDivElement).innerHTML)
                }
                // Initial markup only. Later edits live in the DOM, so React never resets the caret.
                dangerouslySetInnerHTML={{ __html: initialForm.html }}
                style={{
                  minHeight: 280,
                  padding: 12,
                  border: "1px solid #d6dce8",
                  borderRadius: 8,
                  background: "#fff",
                  outline: "none",
                  lineHeight: 1.6,
                }}
              />
            </>
          )}
        </Paper>
      ) : (
        <Stack spacing={2}>
          <TextField
            label="Passing score (%)"
            type="number"
            value={form.passingScore}
            onChange={(e) =>
              update(
                "passingScore",
                Math.min(100, Math.max(0, Number(e.target.value) || 0)),
              )
            }
            sx={{ maxWidth: 220 }}
          />
          {form.questions.map((q, index) => (
            <Card key={index} variant="outlined">
              <CardContent>
                <Stack spacing={2}>
                  <Stack
                    sx={{
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                    direction="row"
                  >
                    <Typography sx={{ fontWeight: 700 }}>
                      Question {index + 1}
                    </Typography>
                    <Button
                      color="error"
                      size="small"
                      onClick={() =>
                        update(
                          "questions",
                          form.questions.filter((_, i) => i !== index),
                        )
                      }
                    >
                      Remove question
                    </Button>
                  </Stack>
                  <TextField
                    label="Prompt"
                    value={q.prompt}
                    multiline
                    minRows={2}
                    onChange={(e) =>
                      updateQuestion(index, { prompt: e.target.value })
                    }
                  />
                  <Stack
                    sx={{ gap: 2 }}
                    direction={{ xs: "column", sm: "row" }}
                  >
                    <TextField
                      select
                      label="Type"
                      value={q.type}
                      sx={{ minWidth: 200 }}
                      onChange={(e) => {
                        const type = e.target.value as QuestionDraft["type"];
                        updateQuestion(index, {
                          type,
                          correct: 0,
                          options:
                            type === "true_false"
                              ? ["True", "False"]
                              : q.options.length >= 2
                                ? q.options
                                : ["", ""],
                        });
                      }}
                    >
                      <MenuItem value="single_choice">Single choice</MenuItem>
                      <MenuItem value="true_false">True / false</MenuItem>
                    </TextField>
                    <TextField
                      label="Points"
                      type="number"
                      value={q.points}
                      sx={{ maxWidth: 120 }}
                      onChange={(e) =>
                        updateQuestion(index, {
                          points: Math.min(
                            100,
                            Math.max(1, Number(e.target.value) || 1),
                          ),
                        })
                      }
                    />
                  </Stack>
                  <Stack spacing={1}>
                    <Typography variant="body2" color="text.secondary">
                      Select the correct answer.
                    </Typography>
                    {q.options.map((option, optionIndex) => (
                      <Stack
                        sx={{ alignItems: "center", gap: 1 }}
                        key={optionIndex}
                        direction="row"
                      >
                        <Radio
                          checked={q.correct === optionIndex}
                          onChange={() =>
                            updateQuestion(index, { correct: optionIndex })
                          }
                          slotProps={{
                            input: {
                              "aria-label": `Option ${optionIndex + 1} is correct`,
                            },
                          }}
                        />
                        {q.type === "true_false" ? (
                          <Typography>{option}</Typography>
                        ) : (
                          <>
                            <TextField
                              size="small"
                              fullWidth
                              value={option}
                              placeholder={`Option ${optionIndex + 1}`}
                              onChange={(e) =>
                                updateQuestion(index, {
                                  options: q.options.map((o, i) =>
                                    i === optionIndex ? e.target.value : o,
                                  ),
                                })
                              }
                            />
                            <IconButton
                              aria-label="Remove option"
                              disabled={q.options.length <= 2}
                              onClick={() =>
                                updateQuestion(index, {
                                  options: q.options.filter(
                                    (_, i) => i !== optionIndex,
                                  ),
                                  correct: Math.min(
                                    q.correct,
                                    q.options.length - 2,
                                  ),
                                })
                              }
                            >
                              ✕
                            </IconButton>
                          </>
                        )}
                      </Stack>
                    ))}
                    {q.type === "single_choice" && q.options.length < 10 && (
                      <Button
                        size="small"
                        sx={{ alignSelf: "flex-start" }}
                        onClick={() =>
                          updateQuestion(index, { options: [...q.options, ""] })
                        }
                      >
                        Add option
                      </Button>
                    )}
                  </Stack>
                  <TextField
                    label="Explanation shown after answering (optional)"
                    value={q.explanation}
                    onChange={(e) =>
                      updateQuestion(index, { explanation: e.target.value })
                    }
                  />
                </Stack>
              </CardContent>
            </Card>
          ))}
          <Button
            variant="outlined"
            disabled={form.questions.length >= 200}
            onClick={() =>
              update("questions", [
                ...form.questions,
                { ...NEW_QUESTION, options: ["", ""] },
              ])
            }
          >
            Add question
          </Button>
        </Stack>
      )}

      {id && <AiAssistPanel loId={id} />}
      <Paper sx={{ p: 2 }}>
        <Stack
          sx={{ justifyContent: "space-between", alignItems: "center" }}
          direction="row"
        >
          <Typography sx={{ fontWeight: 600 }}>Preview</Typography>
          <Button
            size="small"
            disabled={!id}
            onClick={() => setShowPreview((v) => !v)}
          >
            {showPreview ? "Hide preview" : "Show preview"}
          </Button>
        </Stack>
        {!id && (
          <Typography variant="body2" color="text.secondary">
            Preview is available once the item has been saved.
          </Typography>
        )}
        {showPreview && (
          <Stack sx={{ mt: 2 }} spacing={1}>
            <Typography variant="body2" color="text.secondary">
              Shows the last saved version.
            </Typography>
            {preview.isLoading && <Typography>Loading preview…</Typography>}
            {preview.error && (
              <Alert severity="error">{preview.error.message}</Alert>
            )}
            {preview.data && <LibraryPreview item={preview.data} />}
          </Stack>
        )}
      </Paper>
    </Stack>
  );
}
