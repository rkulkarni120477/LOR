"use client";

import { useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
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
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { apiFetch, postJson } from "@/lib/api";
import { can, loadSession } from "@/lib/auth";
import { LibraryPreview, useItemPreview } from "@/components/LibraryPreview";

type Item = {
  id: string;
  title: string;
  kind: "file" | "rich_text" | "quiz" | "assessment";
  status: string;
  is_template: boolean;
  revision: number;
  created_by: string;
  updated_at: string;
  archived_at: string | null;
  deleted_at: string | null;
};
type Listing = { items: Item[]; total: number; page: number; page_size: number };
type Saved = { id: number; name: string; params: Record<string, string | boolean | null> };
type State = "active" | "archived" | "deleted";

const KIND_LABEL: Record<Item["kind"], string> = {
  file: "File",
  rich_text: "Rich text",
  quiz: "Quiz",
  assessment: "Assessment",
};
const EDITABLE = new Set(["rich_text", "quiz", "assessment"]);

export default function Library() {
  const session = loadSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [state, setState] = useState<State>("active");
  const [kind, setKind] = useState("");
  const [template, setTemplate] = useState(false);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveName, setSaveName] = useState("");
  const [showSave, setShowSave] = useState(false);

  const params = new URLSearchParams({ state, page: String(page), page_size: "20" });
  if (kind) params.set("kind", kind);
  if (template) params.set("template", "true");
  if (q.trim()) params.set("q", q.trim());

  const listing = useQuery({
    queryKey: ["library", params.toString()],
    queryFn: () => apiFetch<Listing>(`/v1/library?${params}`),
  });
  const saved = useQuery({
    queryKey: ["library-saved"],
    queryFn: () => apiFetch<{ items: Saved[] }>("/v1/library/saved-searches"),
  });
  const preview = useItemPreview(previewId);

  function refresh() {
    setSelected([]);
    void queryClient.invalidateQueries({ queryKey: ["library"] });
  }

  const act = useMutation({
    mutationFn: async ({ id, action }: { id: string; action: string }) => {
      const method = action === "delete" ? "DELETE" : "POST";
      const path = action === "delete" ? `/v1/library/${id}` : `/v1/library/${id}/${action}`;
      return apiFetch(path, { method });
    },
    onSuccess: () => {
      setNotice(null);
      refresh();
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "Action failed"),
  });

  const bulk = useMutation({
    mutationFn: (action: string) =>
      postJson<{ results: { id: string; ok: boolean; message?: string }[]; succeeded: number }>(
        "/v1/library/bulk",
        { action, ids: selected },
      ),
    onSuccess: (data) => {
      const failed = data.results.filter((r) => !r.ok);
      setNotice(
        failed.length
          ? `${data.succeeded} done, ${failed.length} failed: ${failed.map((f) => f.message).join("; ")}`
          : `${data.succeeded} item(s) updated.`,
      );
      refresh();
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "Bulk action failed"),
  });

  const saveSearch = useMutation({
    mutationFn: () =>
      postJson<Saved>("/v1/library/saved-searches", {
        name: saveName.trim(),
        params: { state, kind: kind || null, template, q: q.trim() || null },
      }),
    onSuccess: () => {
      setShowSave(false);
      setSaveName("");
      void queryClient.invalidateQueries({ queryKey: ["library-saved"] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "Could not save search"),
  });

  const removeSaved = useMutation({
    mutationFn: (id: number) => apiFetch(`/v1/library/saved-searches/${id}`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["library-saved"] }),
  });

  function applySaved(search: Saved) {
    const p = search.params;
    setState((p.state as State) || "active");
    setKind((p.kind as string) || "");
    setTemplate(!!p.template);
    setQ((p.q as string) || "");
    setPage(1);
  }

  function toggle(id: string) {
    setSelected((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );
  }

  const items = listing.data?.items ?? [];
  const allSelected = items.length > 0 && items.every((i) => selected.includes(i.id));
  const canCreate = can(session, "content.create");
  const canEdit = can(session, "content.edit");
  const totalPages = Math.max(1, Math.ceil((listing.data?.total ?? 0) / 20));

  return (
    <Stack spacing={2}>
      <Stack sx={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 1 }} direction="row">
        <Typography sx={{ fontWeight: 700 }} variant="h5">
          Content library
        </Typography>
        {canCreate && (
          <Stack sx={{ gap: 1, flexWrap: "wrap" }} direction="row">
            <Button variant="contained" component={RouterLink} to="/library/new/rich_text">
              New rich text
            </Button>
            <Button variant="outlined" component={RouterLink} to="/library/new/quiz">
              New quiz
            </Button>
            <Button variant="outlined" component={RouterLink} to="/library/new/assessment">
              New assessment
            </Button>
          </Stack>
        )}
      </Stack>

      <Tabs value={state} onChange={(_, value: State) => { setState(value); setPage(1); setSelected([]); }}>
        <Tab value="active" label="Active" />
        <Tab value="archived" label="Archived" />
        <Tab value="deleted" label="Deleted" />
      </Tabs>

      <Paper sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} sx={{ gap: 2, alignItems: { md: "center" } }}>
          <TextField
            label="Search title and content"
            size="small"
            value={q}
            onChange={(e) => { setQ(e.target.value); setPage(1); }}
            sx={{ minWidth: 260 }}
          />
          <TextField select label="Type" size="small" value={kind} onChange={(e) => { setKind(e.target.value); setPage(1); }} sx={{ minWidth: 150 }}>
            <MenuItem value="">All types</MenuItem>
            <MenuItem value="rich_text">Rich text</MenuItem>
            <MenuItem value="quiz">Quiz</MenuItem>
            <MenuItem value="assessment">Assessment</MenuItem>
            <MenuItem value="file">File</MenuItem>
          </TextField>
          <FormControlLabel
            control={<Checkbox checked={template} onChange={(e) => { setTemplate(e.target.checked); setPage(1); }} />}
            label="Templates only"
          />
          <Button size="small" onClick={() => setShowSave((v) => !v)}>
            Save this search
          </Button>
        </Stack>
        {showSave && (
          <Stack direction="row" sx={{ gap: 1,  mt: 2 }}>
            <TextField size="small" label="Name" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
            <Button variant="contained" disabled={!saveName.trim() || saveSearch.isPending} onClick={() => saveSearch.mutate()}>
              Save
            </Button>
          </Stack>
        )}
        {(saved.data?.items ?? []).length > 0 && (
          <Stack direction="row" sx={{ gap: 1, flexWrap: "wrap",  mt: 2 }}>
            {saved.data!.items.map((search) => (
              <Chip
                key={search.id}
                label={search.name}
                onClick={() => applySaved(search)}
                onDelete={() => removeSaved.mutate(search.id)}
                variant="outlined"
              />
            ))}
          </Stack>
        )}
      </Paper>

      {notice && (
        <Alert severity="info" onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}
      {listing.error && <Alert severity="error">{listing.error.message}</Alert>}

      {canEdit && selected.length > 0 && (
        <Paper sx={{ p: 1.5 }}>
          <Stack sx={{ gap: 1, alignItems: "center", flexWrap: "wrap" }} direction="row">
            <Typography variant="body2" sx={{ mr: 1 }}>
              {selected.length} selected
            </Typography>
            {state !== "deleted" && (
              <>
                <Button size="small" onClick={() => bulk.mutate(state === "archived" ? "unarchive" : "archive")}>
                  {state === "archived" ? "Unarchive" : "Archive"}
                </Button>
                <Button size="small" color="error" onClick={() => bulk.mutate("delete")}>
                  Delete
                </Button>
              </>
            )}
            {state === "deleted" && (
              <Button size="small" onClick={() => bulk.mutate("restore")}>
                Restore
              </Button>
            )}
            <Button size="small" onClick={() => setSelected([])}>
              Clear
            </Button>
          </Stack>
        </Paper>
      )}

      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  checked={allSelected}
                  indeterminate={!allSelected && selected.length > 0}
                  onChange={() => setSelected(allSelected ? [] : items.map((i) => i.id))}
                  slotProps={{ input: { "aria-label": "Select all on this page" } }}
                />
              </TableCell>
              <TableCell>Title</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Updated</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id} hover>
                <TableCell padding="checkbox">
                  <Checkbox
                    checked={selected.includes(item.id)}
                    onChange={() => toggle(item.id)}
                    slotProps={{ input: { "aria-label": `Select ${item.title}` } }}
                  />
                </TableCell>
                <TableCell>
                  <Typography sx={{ fontWeight: 600 }}>{item.title}</Typography>
                  <Stack direction="row" sx={{ gap: 0.5,  mt: 0.5 }}>
                    {item.is_template && <Chip size="small" label="Template" />}
                    {item.archived_at && <Chip size="small" label="Archived" />}
                    {item.deleted_at && <Chip size="small" color="error" label="Deleted" />}
                  </Stack>
                </TableCell>
                <TableCell>{KIND_LABEL[item.kind]}</TableCell>
                <TableCell>{new Date(item.updated_at).toLocaleString()}</TableCell>
                <TableCell align="right">
                  <Stack sx={{ gap: 0.5, justifyContent: "flex-end", flexWrap: "wrap" }} direction="row">
                    <Button size="small" onClick={() => setPreviewId(item.id)}>
                      Preview
                    </Button>
                    {canEdit && EDITABLE.has(item.kind) && !item.deleted_at && (
                      <Button size="small" onClick={() => navigate(`/library/${item.id}/edit`)}>
                        Edit
                      </Button>
                    )}
                    {canCreate && !item.deleted_at && (
                      <Button size="small" onClick={() => act.mutate({ id: item.id, action: "duplicate" })}>
                        Duplicate
                      </Button>
                    )}
                    {canEdit && !item.deleted_at && (
                      <Button size="small" onClick={() => act.mutate({ id: item.id, action: item.archived_at ? "unarchive" : "archive" })}>
                        {item.archived_at ? "Unarchive" : "Archive"}
                      </Button>
                    )}
                    {canEdit && !item.deleted_at && (
                      <Button size="small" color="error" onClick={() => act.mutate({ id: item.id, action: "delete" })}>
                        Delete
                      </Button>
                    )}
                    {canEdit && item.deleted_at && (
                      <Button size="small" onClick={() => act.mutate({ id: item.id, action: "restore" })}>
                        Restore
                      </Button>
                    )}
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
            {!listing.isLoading && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={5}>
                  <Typography color="text.secondary">Nothing here yet.</Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <Stack direction="row" sx={{ justifyContent: "flex-end", alignItems: "center", gap: 1,  p: 1 }}>
          <Button size="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <Typography variant="body2">
            Page {page} of {totalPages}
          </Typography>
          <Button size="small" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </Stack>
      </Paper>

      <Dialog open={!!previewId} onClose={() => setPreviewId(null)} maxWidth="md" fullWidth>
        <DialogTitle>{preview.data?.title ?? "Preview"}</DialogTitle>
        <DialogContent dividers>
          {preview.isLoading && <Typography>Loading preview…</Typography>}
          {preview.error && <Alert severity="error">{preview.error.message}</Alert>}
          {preview.data && <LibraryPreview item={preview.data} />}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPreviewId(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
