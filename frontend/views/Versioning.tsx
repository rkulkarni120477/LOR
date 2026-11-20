"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { ApiError, apiFetch, postJson, putJson } from "@/lib/api";
import { loadSession } from "@/lib/auth";

type Snapshot = {
  seq: number;
  label: string;
  kind: "create" | "metadata" | "file" | "restore" | "promote" | "submit";
  file_version: number | null;
  comment: string | null;
  created_by: string;
  created_at: string | null;
  intact: boolean;
};
type History = { current: string | null; items: Snapshot[] };
type Comment = { id: number; author: string; body: string; snapshot_seq: number | null; created_at: string };
type Change = { field: string; from: unknown; to: unknown };
type Diff = { from: string; to: string; changes: Change[]; unchanged: boolean };
type Item = { id: string; title: string; status: string };

const KIND_LABEL: Record<Snapshot["kind"], string> = {
  create: "Created",
  metadata: "Metadata",
  file: "New file (major)",
  restore: "Restored",
  promote: "Promoted (major)",
  submit: "Submitted",
};

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong";
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : String(value);
}

export default function VersioningPage() {
  const session = loadSession();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [viewing, setViewing] = useState<(Snapshot & { content: Record<string, unknown> }) | null>(null);
  const [promoteText, setPromoteText] = useState("");
  const [commentText, setCommentText] = useState("");
  const [commentOn, setCommentOn] = useState("");

  const items = useQuery({
    queryKey: ["version-items"],
    queryFn: () => apiFetch<{ items: Item[] }>("/v1/content?page_size=100"),
  });
  const history = useQuery({
    queryKey: ["versions", selected],
    queryFn: () => apiFetch<History>(`/v1/versions/${selected}`),
    enabled: !!selected,
  });
  const comments = useQuery({
    queryKey: ["version-comments", selected],
    queryFn: () => apiFetch<{ items: Comment[] }>(`/v1/versions/${selected}/comments`),
    enabled: !!selected,
  });
  const diff = useQuery({
    queryKey: ["version-diff", selected, picked],
    queryFn: () => apiFetch<Diff>(`/v1/versions/${selected}/compare?from=${picked[0]}&to=${picked[1]}`),
    enabled: !!selected && picked.length === 2,
  });
  const retention = useQuery({
    queryKey: ["retention"],
    queryFn: () => apiFetch<{ keep_last: number; keep_majors: boolean }>("/v1/versions/retention"),
    enabled: session?.roles.some((r) => r === "Admin" || r === "Repository Administrator" || r === "Super Administrator") ?? false,
    retry: false,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["versions", selected] });
    void queryClient.invalidateQueries({ queryKey: ["version-comments", selected] });
    void queryClient.invalidateQueries({ queryKey: ["version-diff", selected] });
  };
  const fail = (error: unknown) => setMessage(errorText(error));

  const promote = useMutation({
    mutationFn: () => postJson<Snapshot>(`/v1/versions/${selected}/promote`, { comment: promoteText.trim() }),
    onSuccess: (s) => { setPromoteText(""); setMessage(`Promoted to ${s.label}.`); refresh(); },
    onError: fail,
  });
  const restore = useMutation({
    mutationFn: (seq: number) => postJson<{ label: string; note: string }>(`/v1/versions/${selected}/restore`, { seq }),
    onSuccess: (r) => { setMessage(`Restored as ${r.label}: ${r.note}. The item is now a draft.`); setPicked([]); refresh(); },
    onError: fail,
  });
  const addComment = useMutation({
    mutationFn: () => postJson(`/v1/versions/${selected}/comments`, {
      body: commentText.trim(),
      snapshot_seq: commentOn ? Number(commentOn) : null,
    }),
    onSuccess: () => { setCommentText(""); setCommentOn(""); refresh(); },
    onError: fail,
  });
  const saveRetention = useMutation({
    mutationFn: (body: { keep_last: number; keep_majors: boolean }) => putJson("/v1/versions/retention", body),
    onSuccess: () => { setMessage("Retention policy saved."); void queryClient.invalidateQueries({ queryKey: ["retention"] }); },
    onError: fail,
  });
  const applyRetention = useMutation({
    mutationFn: () => postJson<{ removed: number; protected: number }>("/v1/versions/retention/apply", {}),
    onSuccess: (r) => { setMessage(`Retention applied: ${r.removed} snapshot(s) removed, ${r.protected} protected.`); refresh(); },
    onError: fail,
  });

  async function view(snap: Snapshot) {
    try {
      const full = await apiFetch<Snapshot & { content: Record<string, unknown> }>(`/v1/versions/${selected}/snapshots/${snap.seq}`);
      setViewing(full);
    } catch (error) {
      fail(error);
    }
  }

  function togglePick(seq: number) {
    setPicked((current) => {
      if (current.includes(seq)) return current.filter((x) => x !== seq);
      return [...current.slice(-1), seq];
    });
  }

  const snapshots = history.data?.items ?? [];
  const latestSeq = snapshots.length ? snapshots[snapshots.length - 1].seq : null;

  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>Version management</Typography>
      {message && <Alert severity="info" onClose={() => setMessage(null)}>{message}</Alert>}

      <Paper sx={{ p: 2 }}>
        <TextField
          select
          label="Item"
          value={selected ?? ""}
          onChange={(e) => { setSelected(e.target.value); setPicked([]); }}
          sx={{ minWidth: 360 }}
        >
          {(items.data?.items ?? []).map((i) => <MenuItem key={i.id} value={i.id}>{i.title} ({i.status})</MenuItem>)}
        </TextField>
      </Paper>

      {selected && history.data && (
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 1, flexWrap: "wrap", gap: 1 }}>
            <Typography sx={{ fontWeight: 600 }}>History</Typography>
            <Chip label={`Current ${history.data.current ?? "—"}`} />
            <Typography variant="body2" color="text.secondary">
              Tick two versions to compare them. Restore is available for draft or rejected items.
            </Typography>
          </Stack>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox" />
                <TableCell>Version</TableCell>
                <TableCell>Change</TableCell>
                <TableCell>File</TableCell>
                <TableCell>Comment</TableCell>
                <TableCell>By</TableCell>
                <TableCell>When</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {snapshots.map((s) => (
                <TableRow key={s.seq} selected={picked.includes(s.seq)}>
                  <TableCell padding="checkbox">
                    <Checkbox checked={picked.includes(s.seq)} onChange={() => togglePick(s.seq)} />
                  </TableCell>
                  <TableCell>
                    <strong>{s.label}</strong>{" "}
                    {s.seq === latestSeq && <Chip size="small" label="latest" />}
                    {!s.intact && <Chip size="small" color="error" label="integrity failed" sx={{ ml: 1 }} />}
                  </TableCell>
                  <TableCell>{KIND_LABEL[s.kind]}</TableCell>
                  <TableCell>{s.file_version ? `v${s.file_version}` : "—"}</TableCell>
                  <TableCell>{s.comment ?? ""}</TableCell>
                  <TableCell>{s.created_by}</TableCell>
                  <TableCell>{s.created_at ? new Date(s.created_at).toLocaleString() : ""}</TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => view(s)}>View</Button>
                    <Button size="small" disabled={!s.intact || restore.isPending} onClick={() => {
                      if (window.confirm(`Restore ${s.label}? Metadata and the linked file version come back as a new version.`)) restore.mutate(s.seq);
                    }}>Restore</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {picked.length === 2 && diff.data && (
            <Stack spacing={1} sx={{ mt: 2 }}>
              <Typography sx={{ fontWeight: 600 }}>Comparing {diff.data.from} → {diff.data.to}</Typography>
              {diff.data.unchanged && <Typography color="text.secondary">No differences.</Typography>}
              {diff.data.changes.map((c) => (
                <Typography key={c.field} variant="body2">
                  <strong>{c.field}</strong>: {show(c.from)} → {show(c.to)}
                </Typography>
              ))}
            </Stack>
          )}

          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 3 }}>
            <TextField size="small" label="Promote to a new major version: reason" value={promoteText} onChange={(e) => setPromoteText(e.target.value)} fullWidth />
            <Button variant="outlined" disabled={!promoteText.trim() || promote.isPending} onClick={() => promote.mutate()}>Promote</Button>
          </Stack>
        </Paper>
      )}

      {selected && (
        <Paper sx={{ p: 2 }}>
          <Typography sx={{ fontWeight: 600, mb: 1 }}>Comments</Typography>
          <Stack spacing={1}>
            {(comments.data?.items ?? []).map((c) => (
              <Typography key={c.id} variant="body2">
                <strong>{c.author}</strong>{c.snapshot_seq ? ` on version ${snapshots.find((s) => s.seq === c.snapshot_seq)?.label ?? c.snapshot_seq}` : ""}: {c.body}
              </Typography>
            ))}
            {comments.data && comments.data.items.length === 0 && <Typography color="text.secondary">No comments yet.</Typography>}
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 2 }}>
            <TextField select size="small" label="About version" value={commentOn} onChange={(e) => setCommentOn(e.target.value)} sx={{ minWidth: 160 }}>
              <MenuItem value="">The item</MenuItem>
              {snapshots.map((s) => <MenuItem key={s.seq} value={String(s.seq)}>{s.label}</MenuItem>)}
            </TextField>
            <TextField size="small" label="Comment" value={commentText} onChange={(e) => setCommentText(e.target.value)} fullWidth />
            <Button variant="outlined" disabled={!commentText.trim() || addComment.isPending} onClick={() => addComment.mutate()}>Add</Button>
          </Stack>
        </Paper>
      )}

      {retention.data && (
        <RetentionPanel
          keepLast={retention.data.keep_last}
          keepMajors={retention.data.keep_majors}
          onSave={(body) => saveRetention.mutate(body)}
          onApply={() => applyRetention.mutate()}
        />
      )}

      <Dialog open={!!viewing} onClose={() => setViewing(null)} fullWidth maxWidth="md">
        <DialogTitle>Version {viewing?.label}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Immutable snapshot. Recorded {viewing?.created_at ? new Date(viewing.created_at).toLocaleString() : ""}.
          </Typography>
          <Paper variant="outlined" sx={{ p: 1, whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: 12 }}>
            {JSON.stringify(viewing?.content, null, 2)}
          </Paper>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setViewing(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function RetentionPanel({ keepLast, keepMajors, onSave, onApply }: {
  keepLast: number;
  keepMajors: boolean;
  onSave: (body: { keep_last: number; keep_majors: boolean }) => void;
  onApply: () => void;
}) {
  const [last, setLast] = useState(String(keepLast));
  const [majors, setMajors] = useState(keepMajors);
  return (
    <Paper sx={{ p: 2 }}>
      <Typography sx={{ fontWeight: 600, mb: 1 }}>Retention</Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ alignItems: { sm: "center" } }}>
        <TextField size="small" type="number" label="Snapshots kept per item" value={last} onChange={(e) => setLast(e.target.value)} sx={{ maxWidth: 220 }} />
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <Checkbox checked={majors} onChange={(e) => setMajors(e.target.checked)} />
          <Typography variant="body2">Always keep major versions</Typography>
        </Stack>
        <Button variant="outlined" onClick={() => onSave({ keep_last: Number(last), keep_majors: majors })}>Save policy</Button>
        <Button color="error" onClick={() => { if (window.confirm("Remove snapshots beyond the policy now? This cannot be undone.")) onApply(); }}>Apply now</Button>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
        The newest snapshot, approved versions and majors (when kept) are never removed. File bytes are not affected.
      </Typography>
    </Paper>
  );
}
