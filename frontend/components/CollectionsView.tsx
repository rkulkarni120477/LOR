"use client";

import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { apiFetch, postJson, putJson } from "@/lib/api";

type TreeNode = { id: string; name: string; visibility: string; children: TreeNode[] };
type Access = "owner" | "edit" | "view";
type Item = { id: string; title: string; kind?: string; status: string };
type Detail = {
  id: string;
  name: string;
  description: string;
  visibility: "private" | "published";
  owner_subject: string;
  parent_id: string | null;
  access: Access;
  item_count: number;
  breadcrumbs: { id: string; name: string }[];
  children: { id: string; name: string; visibility: string }[];
  items: Item[];
};
type Share = { grantee_type: "user" | "group" | "department"; grantee_id: string; permission: "view" | "edit" };
type Analytics = {
  views: number;
  unique_viewers: number;
  last_viewed_at: string | null;
  views_last_30_days: { date: string; count: number }[];
  direct_items: number;
  subtree_items: number;
  readable_items: number;
  item_status: Record<string, number>;
  child_collections: number;
  subtree_collections: number;
  shares: number;
  favorited_by: number;
};

const ACCESS_LABEL: Record<Access, string> = { owner: "Owner", edit: "Can edit", view: "Can view" };

function flatten(nodes: TreeNode[], depth = 0): { id: string; label: string }[] {
  return nodes.flatMap((n) => [
    { id: n.id, label: `${"— ".repeat(depth)}${n.name}` },
    ...flatten(n.children, depth + 1),
  ]);
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}

export function CollectionsView() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [sort, setSort] = useState<"position" | "title" | "updated">("position");
  const [message, setMessage] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [draft, setDraft] = useState({ name: "", description: "" });
  const [addQuery, setAddQuery] = useState("");

  const tree = useQuery({
    queryKey: ["collections-tree"],
    queryFn: () => apiFetch<{ items: TreeNode[] }>("/v1/collections/tree"),
  });
  const detail = useQuery({
    queryKey: ["collection", selected, sort],
    queryFn: () => apiFetch<Detail>(`/v1/collections/${selected}?sort=${sort}`),
    enabled: !!selected,
  });
  const favorites = useQuery({
    queryKey: ["fav-collections"],
    queryFn: () => apiFetch<{ items: { id: string }[] }>("/v1/favorites/collections"),
  });
  const recent = useQuery({
    queryKey: ["recent"],
    queryFn: () => apiFetch<{ items: { kind: string; id: string; title: string }[] }>("/v1/recent?limit=8"),
  });
  const shares = useQuery({
    queryKey: ["shares", selected],
    queryFn: () => apiFetch<{ items: Share[] }>(`/v1/collections/${selected}/shares`),
    enabled: sharing && !!selected,
    retry: false,
  });
  const stats = useQuery({
    queryKey: ["analytics", selected],
    queryFn: () => apiFetch<Analytics>(`/v1/collections/${selected}/analytics`),
    enabled: analyzing && !!selected,
    retry: false,
  });
  const library = useQuery({
    queryKey: ["library-picker", addQuery],
    queryFn: () =>
      apiFetch<{ items: { id: string; title: string }[] }>(
        `/v1/library?q=${encodeURIComponent(addQuery)}&page_size=10`,
      ),
    enabled: addQuery.trim().length > 0,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["collections-tree"] });
    void queryClient.invalidateQueries({ queryKey: ["collection", selected] });
    void queryClient.invalidateQueries({ queryKey: ["fav-collections"] });
    void queryClient.invalidateQueries({ queryKey: ["recent"] });
  };
  const act = <T,>(run: () => Promise<T>, done?: (value: T) => void) => {
    setMessage(null);
    run()
      .then((value) => {
        done?.(value);
        refresh();
      })
      .catch((error) => setMessage(errorText(error)));
  };

  const current = detail.data;
  const isOwner = current?.access === "owner";
  const canEdit = current?.access === "owner" || current?.access === "edit";
  const isFavorite = !!favorites.data?.items.some((f) => f.id === selected);
  const options = flatten(tree.data?.items ?? []).filter((o) => o.id !== selected);

  const newCollection = useMutation({
    mutationFn: (body: { name: string; description: string; visibility: string; parent_id: string | null }) =>
      postJson<{ id: string }>("/v1/collections", body),
    onSuccess: (created) => {
      setCreating(false);
      setSelected(created.id);
      refresh();
    },
    onError: (error) => setMessage(errorText(error)),
  });
  const deleteOne = useMutation({
    mutationFn: () => apiFetch(`/v1/collections/${selected}`, { method: "DELETE" }),
    onSuccess: () => {
      setSelected(null);
      refresh();
    },
    onError: (error) => setMessage(errorText(error)),
  });

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 1 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          Collections
        </Typography>
        <Button variant="contained" onClick={() => { setDraft({ name: "", description: "" }); setCreating(true); }}>
          New collection
        </Button>
      </Stack>
      {message && <Alert severity="error" onClose={() => setMessage(null)}>{message}</Alert>}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: "flex-start" }}>
        <Paper sx={{ p: 1.5, width: { xs: "100%", md: 300 }, flexShrink: 0 }}>
          <Typography sx={{ fontWeight: 600, px: 1, pb: 1 }}>Folders</Typography>
          {tree.isLoading && <Typography sx={{ px: 1 }}>Loading…</Typography>}
          {(tree.data?.items.length ?? 0) === 0 && !tree.isLoading && (
            <Typography variant="body2" color="text.secondary" sx={{ px: 1 }}>
              No collections yet.
            </Typography>
          )}
          <TreeList nodes={tree.data?.items ?? []} selected={selected} onSelect={setSelected} />
          <Typography sx={{ fontWeight: 600, px: 1, pt: 2, pb: 1 }}>Recently opened</Typography>
          <List dense>
            {(recent.data?.items ?? []).map((r) =>
              r.kind === "collection" ? (
                <ListItemButton key={`c-${r.id}`} onClick={() => setSelected(r.id)}>
                  <ListItemText primary={r.title} secondary="Collection" />
                </ListItemButton>
              ) : (
                <ListItemButton key={`o-${r.id}`} component={RouterLink} to={`/objects?id=${r.id}`}>
                  <ListItemText primary={r.title} secondary="Object" />
                </ListItemButton>
              ),
            )}
            {(recent.data?.items ?? []).length === 0 && (
              <Typography variant="body2" color="text.secondary" sx={{ px: 1 }}>
                Nothing opened yet.
              </Typography>
            )}
          </List>
        </Paper>

        <Stack spacing={2} sx={{ flex: 1, minWidth: 0, width: "100%" }}>
          {!selected && (
            <Paper sx={{ p: 3 }}>
              <Typography color="text.secondary">Select a collection to see its contents.</Typography>
            </Paper>
          )}
          {selected && detail.isLoading && <Typography>Loading…</Typography>}
          {selected && detail.error && <Alert severity="error">{errorText(detail.error)}</Alert>}
          {current && (
            <>
              <Paper sx={{ p: 3 }}>
                <Stack spacing={2}>
                  <Typography variant="body2" color="text.secondary">
                    {current.breadcrumbs.map((b, i) => (
                      <span key={b.id}>
                        {i > 0 && " / "}
                        <Button size="small" onClick={() => setSelected(b.id)} sx={{ minWidth: 0, p: 0 }}>
                          {b.name}
                        </Button>
                      </span>
                    ))}
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                    <Typography variant="h5" sx={{ fontWeight: 700 }}>
                      {current.name}
                    </Typography>
                    <Chip size="small" label={current.visibility === "published" ? "Published" : "Private"} />
                    <Chip size="small" variant="outlined" label={ACCESS_LABEL[current.access]} />
                    <Button size="small" onClick={() => act(() => apiFetch(`/v1/favorites/collections/${selected}`, { method: isFavorite ? "DELETE" : "PUT" }))}>
                      {isFavorite ? "★ Favorited" : "☆ Favorite"}
                    </Button>
                  </Stack>
                  {current.description && <Typography>{current.description}</Typography>}

                  <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
                    {canEdit && (
                      <Button size="small" variant="outlined" onClick={() => { setDraft({ name: current.name, description: current.description }); }}>
                        Edit details
                      </Button>
                    )}
                    <Button size="small" variant="outlined" onClick={() => act(() => postJson(`/v1/collections/${selected}/duplicate`, {}), (r) => setMessage(`Copied ${(r as { collections: number }).collections} collection(s) and ${(r as { items: number }).items} item(s).`))}>
                      Duplicate
                    </Button>
                    <Button size="small" variant="outlined" onClick={() => setAnalyzing(true)} disabled={!canEdit}>
                      Analytics
                    </Button>
                    {isOwner && (
                      <>
                        <Button size="small" variant="outlined" onClick={() => setSharing(true)}>
                          Share
                        </Button>
                        <Button size="small" variant="outlined" onClick={() => act(() => putJson(`/v1/collections/${selected}/publish`, { published: current.visibility !== "published" }))}>
                          {current.visibility === "published" ? "Unpublish" : "Publish"}
                        </Button>
                        <TextField
                          select
                          size="small"
                          label="Move under"
                          value={current.parent_id ?? ""}
                          onChange={(e) => act(() => putJson(`/v1/collections/${selected}/move`, { parent_id: e.target.value || null }))}
                          sx={{ minWidth: 200 }}
                        >
                          <MenuItem value="">Top level</MenuItem>
                          {options.map((o) => (
                            <MenuItem key={o.id} value={o.id}>{o.label}</MenuItem>
                          ))}
                        </TextField>
                        <Button size="small" color="error" onClick={() => { if (window.confirm("Delete this collection and everything inside it?")) deleteOne.mutate(); }}>
                          Delete
                        </Button>
                      </>
                    )}
                  </Stack>

                  {draft.name !== "" && canEdit && (
                    <Stack spacing={1}>
                      <TextField label="Name" size="small" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                      <TextField label="Description" size="small" multiline minRows={2} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                      <Stack direction="row" spacing={1}>
                        <Button variant="contained" size="small" onClick={() => act(() => putJson(`/v1/collections/${selected}`, { name: draft.name, description: draft.description }), () => setDraft({ name: "", description: "" }))}>
                          Save details
                        </Button>
                        <Button size="small" onClick={() => setDraft({ name: "", description: "" })}>Cancel</Button>
                      </Stack>
                    </Stack>
                  )}
                </Stack>
              </Paper>

              {current.children.length > 0 && (
                <Paper sx={{ p: 2 }}>
                  <Typography sx={{ fontWeight: 600, mb: 1 }}>Inside this collection</Typography>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
                    {current.children.map((child) => (
                      <Chip key={child.id} label={child.name} onClick={() => setSelected(child.id)} variant="outlined" />
                    ))}
                  </Stack>
                </Paper>
              )}

              <Paper sx={{ p: 2 }}>
                <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 1, mb: 1 }}>
                  <Typography sx={{ fontWeight: 600 }}>Items ({current.items.length})</Typography>
                  <TextField select size="small" label="Sort" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} sx={{ minWidth: 160 }}>
                    <MenuItem value="position">Manual order</MenuItem>
                    <MenuItem value="title">Title</MenuItem>
                    <MenuItem value="updated">Recently updated</MenuItem>
                  </TextField>
                </Stack>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Title</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="right" />
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {current.items.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell>{item.title}</TableCell>
                        <TableCell>{item.status}</TableCell>
                        <TableCell align="right">
                          {canEdit && (
                            <Button size="small" color="error" onClick={() => act(() => putJson(`/v1/collections/${selected}/items`, { object_ids: current.items.filter((i) => i.id !== item.id).map((i) => i.id) }))}>
                              Remove
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                    {current.items.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={3}>
                          <Typography color="text.secondary">No items you can see here.</Typography>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
                {canEdit && (
                  <Stack spacing={1} sx={{ mt: 2 }}>
                    <TextField size="small" label="Add from your library" value={addQuery} onChange={(e) => setAddQuery(e.target.value)} />
                    {(library.data?.items ?? [])
                      .filter((r) => !current.items.some((i) => i.id === r.id))
                      .map((r) => (
                        <Stack key={r.id} direction="row" spacing={1} sx={{ alignItems: "center" }}>
                          <Typography sx={{ flex: 1 }}>{r.title}</Typography>
                          <Button size="small" onClick={() => act(() => putJson(`/v1/collections/${selected}/items`, { object_ids: [...current.items.map((i) => i.id), r.id] }))}>
                            Add
                          </Button>
                        </Stack>
                      ))}
                  </Stack>
                )}
              </Paper>
            </>
          )}
        </Stack>
      </Stack>

      <Dialog open={creating} onClose={() => setCreating(false)} fullWidth maxWidth="sm">
        <NewCollectionForm
          options={flatten(tree.data?.items ?? [])}
          parentDefault={selected}
          busy={newCollection.isPending}
          onCancel={() => setCreating(false)}
          onSubmit={(body) => newCollection.mutate(body)}
        />
      </Dialog>

      <Dialog open={sharing} onClose={() => setSharing(false)} fullWidth maxWidth="sm">
        <DialogTitle>Share “{current?.name}”</DialogTitle>
        <ShareForm
          shares={shares.data?.items ?? []}
          loading={shares.isLoading}
          error={shares.error ? errorText(shares.error) : null}
          onAdd={(share) => act(() => putJson(`/v1/collections/${selected}/shares`, share))}
          onRemove={(s) => act(() => apiFetch(`/v1/collections/${selected}/shares/${s.grantee_type}/${s.grantee_id}`, { method: "DELETE" }))}
          onClose={() => setSharing(false)}
        />
      </Dialog>

      <Dialog open={analyzing} onClose={() => setAnalyzing(false)} fullWidth maxWidth="sm">
        <DialogTitle>Analytics</DialogTitle>
        <DialogContent dividers>
          {stats.isLoading && <Typography>Loading…</Typography>}
          {stats.error && <Alert severity="error">{errorText(stats.error)}</Alert>}
          {stats.data && (
            <Stack spacing={1}>
              <Typography>Views: {stats.data.views} · unique viewers: {stats.data.unique_viewers}</Typography>
              <Typography>Last viewed: {stats.data.last_viewed_at ? new Date(stats.data.last_viewed_at).toLocaleString() : "never"}</Typography>
              <Typography>Items: {stats.data.direct_items} here, {stats.data.subtree_items} in total ({stats.data.readable_items} you can read)</Typography>
              <Typography>Status: {Object.entries(stats.data.item_status).map(([k, v]) => `${k} ${v}`).join(", ") || "no readable items"}</Typography>
              <Typography>Sub-collections: {stats.data.child_collections} direct, {stats.data.subtree_collections} in total</Typography>
              <Typography>Shares: {stats.data.shares} · favorited by {stats.data.favorited_by}</Typography>
              <Typography sx={{ fontWeight: 600, mt: 1 }}>Views, last 30 days</Typography>
              {stats.data.views_last_30_days.length === 0 && <Typography color="text.secondary">No views in the last 30 days.</Typography>}
              {stats.data.views_last_30_days.map((d) => (
                <Typography key={d.date} variant="body2">{d.date}: {d.count}</Typography>
              ))}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAnalyzing(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function TreeList({ nodes, selected, onSelect, depth = 0 }: {
  nodes: TreeNode[];
  selected: string | null;
  onSelect: (id: string) => void;
  depth?: number;
}) {
  return (
    <List dense disablePadding>
      {nodes.map((node) => (
        <div key={node.id}>
          <ListItemButton selected={node.id === selected} onClick={() => onSelect(node.id)} sx={{ pl: 1 + depth * 2 }}>
            <ListItemText primary={node.name} secondary={node.visibility === "published" ? "Published" : undefined} />
          </ListItemButton>
          {node.children.length > 0 && (
            <TreeList nodes={node.children} selected={selected} onSelect={onSelect} depth={depth + 1} />
          )}
        </div>
      ))}
    </List>
  );
}

function NewCollectionForm({ options, parentDefault, busy, onCancel, onSubmit }: {
  options: { id: string; label: string }[];
  parentDefault: string | null;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (body: { name: string; description: string; visibility: string; parent_id: string | null }) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [parent, setParent] = useState(parentDefault ?? "");
  const [published, setPublished] = useState(false);
  return (
    <>
      <DialogTitle>New collection</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Description" multiline minRows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          <TextField select label="Inside" value={parent} onChange={(e) => setParent(e.target.value)}>
            <MenuItem value="">Top level</MenuItem>
            {options.map((o) => (
              <MenuItem key={o.id} value={o.id}>{o.label}</MenuItem>
            ))}
          </TextField>
          <FormControlLabel control={<Switch checked={published} onChange={(e) => setPublished(e.target.checked)} />} label="Publish to everyone who can read content" />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || busy} onClick={() => onSubmit({ name, description, visibility: published ? "published" : "private", parent_id: parent || null })}>
          Create
        </Button>
      </DialogActions>
    </>
  );
}

function ShareForm({ shares, loading, error, onAdd, onRemove, onClose }: {
  shares: Share[];
  loading: boolean;
  error: string | null;
  onAdd: (share: Share) => void;
  onRemove: (share: Share) => void;
  onClose: () => void;
}) {
  const [type, setType] = useState<Share["grantee_type"]>("user");
  const [id, setId] = useState("");
  const [permission, setPermission] = useState<Share["permission"]>("view");
  return (
    <>
      <DialogContent dividers>
        {error && <Alert severity="error">{error}</Alert>}
        {loading && <Typography>Loading…</Typography>}
        <Stack spacing={1} sx={{ mb: 2 }}>
          {shares.map((s) => (
            <Stack key={`${s.grantee_type}-${s.grantee_id}`} direction="row" spacing={1} sx={{ alignItems: "center" }}>
              <Typography sx={{ flex: 1 }}>{s.grantee_type} {s.grantee_id}</Typography>
              <Chip size="small" label={s.permission} />
              <IconButton aria-label="Remove share" onClick={() => onRemove(s)}>✕</IconButton>
            </Stack>
          ))}
          {!loading && !error && shares.length === 0 && <Typography color="text.secondary">Not shared with anyone yet.</Typography>}
        </Stack>
        <Stack spacing={2}>
          <TextField select label="Share with" value={type} onChange={(e) => setType(e.target.value as Share["grantee_type"])}>
            <MenuItem value="user">A person (sign-in name)</MenuItem>
            <MenuItem value="group">A group (numeric id)</MenuItem>
            <MenuItem value="department">A department (numeric id)</MenuItem>
          </TextField>
          <TextField label={type === "user" ? "Sign-in name (subject)" : "Id"} value={id} onChange={(e) => setId(e.target.value)} />
          <TextField select label="Permission" value={permission} onChange={(e) => setPermission(e.target.value as Share["permission"])}>
            <MenuItem value="view">Can view</MenuItem>
            <MenuItem value="edit">Can edit items</MenuItem>
          </TextField>
          <Button variant="outlined" disabled={!id.trim()} onClick={() => { onAdd({ grantee_type: type, grantee_id: id.trim(), permission }); setId(""); }}>
            Add share
          </Button>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Done</Button>
      </DialogActions>
    </>
  );
}
