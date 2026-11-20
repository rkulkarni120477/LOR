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
import { apiFetch, postJson, putJson } from "@/lib/api";

type Folder = { name: string; count: number; system: boolean };
type FavoriteObject = { id: string; title: string; status: string; folder: string };
type FavoriteCollection = { id: string; name: string; access: string; item_count?: number };

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}

export function FavoritesView() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"objects" | "collections" | "folders">("objects");
  const [message, setMessage] = useState<string | null>(null);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["favorites"] });
    void queryClient.invalidateQueries({ queryKey: ["folders"] });
    void queryClient.invalidateQueries({ queryKey: ["fav-collections"] });
    void queryClient.invalidateQueries({ queryKey: ["collections-tree"] });
  };
  const run = (action: () => Promise<unknown>) => {
    setMessage(null);
    action().then(refresh).catch((error) => setMessage(errorText(error)));
  };

  return (
    <Stack spacing={2}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Favorites
      </Typography>
      {message && <Alert severity="error" onClose={() => setMessage(null)}>{message}</Alert>}
      <Tabs value={tab} onChange={(_, value) => setTab(value)}>
        <Tab value="objects" label="Learning objects" />
        <Tab value="collections" label="Collections" />
        <Tab value="folders" label="Folders" />
      </Tabs>
      {tab === "objects" && <ObjectFavorites onAction={run} />}
      {tab === "collections" && <CollectionFavorites onAction={run} />}
      {tab === "folders" && <FolderManager onAction={run} onError={setMessage} />}
    </Stack>
  );
}

function ObjectFavorites({ onAction }: { onAction: (action: () => Promise<unknown>) => void }) {
  const [folder, setFolder] = useState("");
  const [sort, setSort] = useState<"added" | "title">("added");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const folders = useQuery({
    queryKey: ["folders"],
    queryFn: () => apiFetch<{ details: Folder[] }>("/v1/favorites/folders"),
  });
  const params = new URLSearchParams({ sort, order, page: String(page), page_size: "20" });
  if (folder) params.set("folder", folder);
  if (q.trim()) params.set("q", q.trim());
  const favorites = useQuery({
    queryKey: ["favorites", params.toString()],
    queryFn: () => apiFetch<{ items: FavoriteObject[]; total: number }>(`/v1/favorites?${params}`),
  });
  const totalPages = Math.max(1, Math.ceil((favorites.data?.total ?? 0) / 20));

  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2, alignItems: { md: "center" } }}>
        <TextField size="small" label="Search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <TextField select size="small" label="Folder" value={folder} onChange={(e) => { setFolder(e.target.value); setPage(1); }} sx={{ minWidth: 200 }}>
          <MenuItem value="">All folders</MenuItem>
          {(folders.data?.details ?? []).map((f) => (
            <MenuItem key={f.name} value={f.name}>{f.name} ({f.count})</MenuItem>
          ))}
        </TextField>
        <TextField select size="small" label="Sort by" value={sort} onChange={(e) => setSort(e.target.value as "added" | "title")} sx={{ minWidth: 160 }}>
          <MenuItem value="added">Date added</MenuItem>
          <MenuItem value="title">Title</MenuItem>
        </TextField>
        <TextField select size="small" label="Order" value={order} onChange={(e) => setOrder(e.target.value as "asc" | "desc")} sx={{ minWidth: 120 }}>
          <MenuItem value="asc">Ascending</MenuItem>
          <MenuItem value="desc">Descending</MenuItem>
        </TextField>
      </Stack>
      {favorites.error && <Alert severity="error">{errorText(favorites.error)}</Alert>}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Title</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Folder</TableCell>
            <TableCell align="right" />
          </TableRow>
        </TableHead>
        <TableBody>
          {(favorites.data?.items ?? []).map((item) => (
            <TableRow key={item.id}>
              <TableCell>
                <Button component={RouterLink} to={`/objects?id=${item.id}`} size="small">{item.title}</Button>
              </TableCell>
              <TableCell>{item.status}</TableCell>
              <TableCell>
                <TextField
                  select
                  size="small"
                  value={item.folder}
                  onChange={(e) => onAction(() => putJson(`/v1/favorites/${item.id}`, { folder: e.target.value }))}
                  sx={{ minWidth: 180 }}
                  slotProps={{ htmlInput: { "aria-label": `Folder for ${item.title}` } }}
                >
                  {(folders.data?.details ?? []).map((f) => (
                    <MenuItem key={f.name} value={f.name}>{f.name}</MenuItem>
                  ))}
                </TextField>
              </TableCell>
              <TableCell align="right">
                <Button size="small" color="error" onClick={() => onAction(() => apiFetch(`/v1/favorites/${item.id}`, { method: "DELETE" }))}>
                  Remove
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {favorites.data && favorites.data.items.length === 0 && (
            <TableRow>
              <TableCell colSpan={4}>
                <Typography color="text.secondary">No favorites here.</Typography>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <Stack direction="row" sx={{ justifyContent: "flex-end", alignItems: "center", gap: 1, mt: 2 }}>
        <Button size="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
        <Typography variant="body2">Page {page} of {totalPages}</Typography>
        <Button size="small" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</Button>
      </Stack>
    </Paper>
  );
}

function CollectionFavorites({ onAction }: { onAction: (action: () => Promise<unknown>) => void }) {
  const collections = useQuery({
    queryKey: ["fav-collections"],
    queryFn: () => apiFetch<{ items: FavoriteCollection[] }>("/v1/favorites/collections"),
  });
  return (
    <Paper sx={{ p: 2 }}>
      <Stack spacing={1}>
        {(collections.data?.items ?? []).map((c) => (
          <Stack key={c.id} direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Button component={RouterLink} to="/collections" sx={{ flex: 1, justifyContent: "flex-start" }}>
              {c.name}
            </Button>
            <Chip size="small" variant="outlined" label={c.access === "owner" ? "Owner" : c.access === "edit" ? "Can edit" : "Can view"} />
            <Button size="small" onClick={() => onAction(() => apiFetch(`/v1/favorites/collections/${c.id}`, { method: "DELETE" }))}>
              Unfavorite
            </Button>
          </Stack>
        ))}
        {collections.data && collections.data.items.length === 0 && (
          <Typography color="text.secondary">No favorite collections. Star one from the Collections page.</Typography>
        )}
      </Stack>
    </Paper>
  );
}

function FolderManager({ onAction, onError }: {
  onAction: (action: () => Promise<unknown>) => void;
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<Folder | null>(null);
  const [renameTo, setRenameTo] = useState("");
  const [deleting, setDeleting] = useState<Folder | null>(null);
  const [moveTo, setMoveTo] = useState("");
  const folders = useQuery({
    queryKey: ["folders"],
    queryFn: () => apiFetch<{ details: Folder[] }>("/v1/favorites/folders"),
  });
  const create = useMutation({
    mutationFn: (name: string) => postJson("/v1/favorites/folders", { name }),
    onSuccess: () => {
      setNewName("");
      void queryClient.invalidateQueries({ queryKey: ["folders"] });
    },
    onError: (error) => onError(errorText(error)),
  });

  return (
    <Paper sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <TextField size="small" label="New folder" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <Button variant="contained" disabled={!newName.trim() || create.isPending} onClick={() => create.mutate(newName.trim())}>
            Create
          </Button>
        </Stack>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Folder</TableCell>
              <TableCell>Favorites</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(folders.data?.details ?? []).map((f) => (
              <TableRow key={f.name}>
                <TableCell>
                  {f.name} {f.system && <Chip size="small" label="System" sx={{ ml: 1 }} />}
                </TableCell>
                <TableCell>{f.count}</TableCell>
                <TableCell align="right">
                  {!f.system && (
                    <>
                      <Button size="small" onClick={() => { setRenaming(f); setRenameTo(f.name); }}>Rename</Button>
                      <Button size="small" color="error" onClick={() => { setDeleting(f); setMoveTo(""); }}>Delete</Button>
                    </>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Stack>

      <Dialog open={!!renaming} onClose={() => setRenaming(null)}>
        <DialogTitle>Rename folder</DialogTitle>
        <DialogContent>
          <TextField autoFocus fullWidth label="Name" value={renameTo} onChange={(e) => setRenameTo(e.target.value)} sx={{ mt: 1 }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRenaming(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!renameTo.trim()}
            onClick={() => {
              const from = renaming!.name;
              const to = renameTo.trim();
              setRenaming(null);
              onAction(() => putJson(`/v1/favorites/folders/${encodeURIComponent(from)}`, { name: to }));
            }}
          >
            Rename
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!deleting} onClose={() => setDeleting(null)}>
        <DialogTitle>Delete folder “{deleting?.name}”</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>
            Its {deleting?.count ?? 0} favorite(s) move to the folder you choose.
          </Typography>
          <TextField
            select
            fullWidth
            label="Move favorites to"
            value={moveTo}
            onChange={(e) => setMoveTo(e.target.value)}
          >
            {(folders.data?.details ?? []).filter((f) => f.name !== deleting?.name).map((f) => (
              <MenuItem key={f.name} value={f.name}>{f.name}</MenuItem>
            ))}
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleting(null)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            disabled={!moveTo}
            onClick={() => {
              const name = deleting!.name;
              const target = moveTo;
              setDeleting(null);
              onAction(() => apiFetch(`/v1/favorites/folders/${encodeURIComponent(name)}?move_to=${encodeURIComponent(target)}`, { method: "DELETE" }));
            }}
          >
            Delete folder
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
