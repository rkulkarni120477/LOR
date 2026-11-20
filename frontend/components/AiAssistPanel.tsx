"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Chip, FormControlLabel, Paper, Stack, TextField, Typography } from "@mui/material";
import { ApiError, apiFetch, postJson, putJson } from "@/lib/api";
import { loadSession } from "@/lib/auth";

type Suggestion = {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  generator: string;
  status: "pending" | "accepted" | "rejected";
  requested_by: string;
  decided_by: string | null;
  decision_note: string | null;
  edited: boolean;
};

const KINDS = ["outline", "objectives", "summary", "quiz", "metadata", "classification", "accessibility"] as const;

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong";
}

/** Drafts for a learning object. Nothing here changes the item until a second person accepts it. */
export function AiAssistPanel({ loId }: { loId: string }) {
  const queryClient = useQueryClient();
  const session = loadSession();
  const [picked, setPicked] = useState<string[]>(["outline", "objectives", "summary", "quiz"]);
  const [message, setMessage] = useState<string | null>(null);
  const suggestions = useQuery({
    queryKey: ["ai-suggestions", loId],
    queryFn: () => apiFetch<{ items: Suggestion[] }>(`/v1/ai/${loId}/suggestions`),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["ai-suggestions", loId] });
    void queryClient.invalidateQueries({ queryKey: ["library-item", loId] });
  };
  const generate = useMutation({
    mutationFn: () => postJson(`/v1/ai/${loId}/suggestions`, { kinds: picked }),
    onSuccess: () => { setMessage("Drafts added for review. Nothing has changed on the item yet."); refresh(); },
    onError: (e) => setMessage(errorText(e)),
  });

  return (
    <Paper sx={{ p: 2 }}>
      <Typography sx={{ fontWeight: 600 }}>AI-assisted drafts</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Suggestions are reviewed by a person. You cannot accept a draft you requested; a second reviewer does that.
      </Typography>
      {message && <Alert severity="info" onClose={() => setMessage(null)} sx={{ mb: 1 }}>{message}</Alert>}
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1, mb: 1 }}>
        {KINDS.map((k) => (
          <FormControlLabel
            key={k}
            control={<Checkbox size="small" checked={picked.includes(k)} onChange={(e) => setPicked(e.target.checked ? [...picked, k] : picked.filter((x) => x !== k))} />}
            label={k}
          />
        ))}
      </Stack>
      <Button variant="outlined" disabled={picked.length === 0 || generate.isPending} onClick={() => generate.mutate()}>
        Draft suggestions
      </Button>

      <Stack spacing={2} sx={{ mt: 2 }}>
        {(suggestions.data?.items ?? []).map((s) => (
          <SuggestionCard key={s.id} suggestion={s} viewer={session?.subject ?? ""} onChanged={refresh} onError={(e) => setMessage(errorText(e))} />
        ))}
      </Stack>
    </Paper>
  );
}

function SuggestionCard({ suggestion, viewer, onChanged, onError }: {
  suggestion: Suggestion;
  viewer: string;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const [text, setText] = useState(JSON.stringify(suggestion.payload, null, 2));
  const [note, setNote] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const pending = suggestion.status === "pending";
  const isRequester = viewer === suggestion.requested_by;
  const save = useMutation({
    mutationFn: (payload: Record<string, unknown>) => putJson(`/v1/ai/suggestions/${suggestion.id}`, { payload }),
    onSuccess: onChanged,
    onError,
  });
  const decide = useMutation({
    mutationFn: (decision: "accept" | "reject") => postJson(`/v1/ai/suggestions/${suggestion.id}/${decision}`, { note: note || null }),
    onSuccess: onChanged,
    onError,
  });

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", gap: 1 }}>
        <Typography sx={{ fontWeight: 600 }}>{suggestion.kind}</Typography>
        <Chip size="small" label={suggestion.generator} />
        <Chip size="small" color={suggestion.status === "accepted" ? "success" : suggestion.status === "rejected" ? "default" : "warning"} label={suggestion.status} />
        {suggestion.edited && <Chip size="small" variant="outlined" label="edited" />}
        {suggestion.decided_by && <Typography variant="caption">decided by {suggestion.decided_by}</Typography>}
      </Stack>
      {suggestion.decision_note && <Typography variant="body2" sx={{ mt: 1 }}>Note: {suggestion.decision_note}</Typography>}
      {pending && (
        <Stack spacing={1} sx={{ mt: 1 }}>
          <TextField
            multiline
            minRows={4}
            size="small"
            label="Draft (JSON)"
            value={text}
            error={!!parseError}
            helperText={parseError ?? "Edit the draft before you accept it, if needed."}
            onChange={(e) => setText(e.target.value)}
          />
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
            <Button size="small" onClick={() => {
              try {
                save.mutate(JSON.parse(text));
                setParseError(null);
              } catch {
                setParseError("This is not valid JSON.");
              }
            }}>Save edits</Button>
            <TextField size="small" label="Review note" value={note} onChange={(e) => setNote(e.target.value)} sx={{ minWidth: 240 }} />
            <Button size="small" variant="contained" disabled={isRequester || decide.isPending} onClick={() => decide.mutate("accept")}>
              Accept
            </Button>
            <Button size="small" color="error" disabled={!note.trim() || decide.isPending} onClick={() => decide.mutate("reject")}>
              Reject
            </Button>
          </Stack>
          {isRequester && <Typography variant="caption" color="text.secondary">You requested this draft, so a second reviewer must accept or reject it.</Typography>}
        </Stack>
      )}
    </Paper>
  );
}
