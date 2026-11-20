"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import Link from "@/components/Link";
import { apiBlob, apiFetch, postJson, putJson } from "@/lib/api";
import { hasAnyRole, loadSession } from "@/lib/auth";

type ObjectRow = { id: string; title: string; status: string };
type Collection = {
  id: string;
  name: string;
  description: string;
  visibility: string;
  owner_subject: string;
  items: ObjectRow[];
};
type Page<T> = { items: T[]; total: number };
type Detail = ObjectRow & {
  versions: {
    version_number: number;
    original_filename: string;
    size_bytes: number;
  }[];
};
type CollectionForm = { name: string; description: string; visibility: string };

export function OrganizationWorkspace({
  mode,
}: {
  mode: "collections" | "favorites" | "versioning";
}) {
  const client = useQueryClient();
  const session = loadSession();
  const canEdit = hasAnyRole(session, ["Contributor"]);
  const [page, setPage] = useState(1);
  const [folder, setFolder] = useState("AI in Education");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState("");
  const [activeId, setActiveId] = useState("");
  const [message, setMessage] = useState("");
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CollectionForm>({
    defaultValues: { name: "", description: "", visibility: "private" },
  });
  const objects = useQuery({
    queryKey: ["objects"],
    queryFn: () => apiFetch<Page<ObjectRow>>("/v1/content?page_size=100"),
  });
  const folders = useQuery({
    queryKey: ["favorite-folders"],
    queryFn: () => apiFetch<{ items: string[] }>("/v1/favorites/folders"),
    enabled: mode === "favorites",
  });
  const list = useQuery({
    queryKey: [mode, page, folder, search],
    enabled: mode !== "versioning",
    queryFn: () =>
      apiFetch<Page<Collection & ObjectRow>>(
        mode === "collections"
          ? `/v1/collections?page=${page}`
          : `/v1/favorites?page=${page}&folder=${encodeURIComponent(folder)}&q=${encodeURIComponent(search)}`,
      ),
  });
  const active = useQuery({
    queryKey: ["collection", activeId],
    enabled: !!activeId,
    queryFn: () => apiFetch<Collection>(`/v1/collections/${activeId}`),
  });
  const detail = useQuery({
    queryKey: ["object", selected],
    enabled: mode === "versioning" && !!selected,
    queryFn: () => apiFetch<Detail>(`/v1/content/${selected}`),
  });
  const mutation = useMutation({
    mutationFn: async (action: () => Promise<unknown>) => action(),
    onSuccess: async () => {
      await client.invalidateQueries();
      setMessage("Changes saved.");
    },
  });
  function run(action: () => Promise<unknown>) {
    setMessage("");
    mutation.mutate(action);
  }
  async function saveItems(ids: string[]) {
    return putJson(`/v1/collections/${activeId}/items`, { object_ids: ids });
  }
  async function download(id: string, version?: number) {
    const blob = await apiBlob(
      `/v1/content/${id}/download${version ? `?version=${version}` : ""}`,
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download =
      detail.data?.versions.find((v) => v.version_number === version)
        ?.original_filename || "learning-object";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const error =
    objects.error ||
    list.error ||
    folders.error ||
    active.error ||
    detail.error ||
    mutation.error;
  const owned =
    active.data &&
    (active.data.owner_subject === session?.subject ||
      hasAnyRole(session, ["Admin"]));
  const pending = mutation.isPending;

  return (
    <Stack spacing={3}>
      <Typography variant="body2">
        <Link href="/">Home</Link> / {mode}
      </Typography>
      <Typography
        variant="h4"
        component="h1"
        sx={{ textTransform: "capitalize" }}
      >
        {mode}
      </Typography>
      <Typography>
        {mode === "collections"
          ? "Organize reusable content in private or shared collections."
          : mode === "favorites"
            ? "Keep personal learning resources in folders."
            : "Inspect file history and restore a previous file as a new draft. Current metadata is retained."}
      </Typography>
      {error && <Alert severity="error">{error.message}</Alert>}
      {message && <Alert severity="success">{message}</Alert>}
      {(objects.isLoading || (list.isLoading && mode !== "versioning")) && (
        <CircularProgress aria-label="Loading repository" />
      )}
      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        {mode === "favorites" && (
          <>
            <FormControl sx={{ minWidth: 190 }}>
              <InputLabel id="folder-label">Folder</InputLabel>
              <Select
                labelId="folder-label"
                label="Folder"
                value={folder}
                onChange={(e) => {
                  setFolder(e.target.value);
                  setPage(1);
                }}
              >
                {(
                  folders.data?.items || [
                    "AI in Education",
                    "Leadership",
                    "Product Training",
                  ]
                ).map((f) => (
                  <MenuItem key={f} value={f}>
                    {f}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Search favorites"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </>
        )}
        <FormControl sx={{ minWidth: 240, maxWidth: "100%" }}>
          <InputLabel id="object-label">Learning object</InputLabel>
          <Select
            labelId="object-label"
            label="Learning object"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <MenuItem value="">Select an object</MenuItem>
            {objects.data?.items.map((o) => (
              <MenuItem key={o.id} value={o.id}>
                {o.title} ({o.status})
              </MenuItem>
            ))}
          </Select>
          <Typography variant="caption">
            Most recent 100 accessible objects
          </Typography>
        </FormControl>
        {mode === "favorites" && (
          <Button
            disabled={pending || !selected}
            variant="contained"
            onClick={() =>
              run(() => putJson(`/v1/favorites/${selected}`, { folder }))
            }
          >
            Save favorite
          </Button>
        )}
      </Stack>
      {mode === "collections" && (
        <>
          {canEdit && (
            <Card variant="outlined">
              <CardContent>
                <Box
                  component="form"
                  onSubmit={handleSubmit(async (data) => {
                    try {
                      await mutation.mutateAsync(() =>
                        postJson("/v1/collections", data),
                      );
                      reset();
                    } catch {
                      /* mutation error is displayed above */
                    }
                  })}
                >
                  <Stack spacing={2}>
                    <Typography variant="h6" component="h2">
                      Create collection
                    </Typography>
                    <TextField
                      label="Collection name"
                      error={!!errors.name}
                      helperText={errors.name?.message}
                      {...register("name", {
                        required: "Name is required",
                        maxLength: {
                          value: 255,
                          message: "Use at most 255 characters",
                        },
                        validate: (v) => !!v.trim() || "Enter a name",
                      })}
                    />
                    <TextField
                      label="Description"
                      multiline
                      rows={2}
                      {...register("description", { maxLength: 5000 })}
                    />
                    <TextField
                      select
                      label="Visibility"
                      defaultValue="private"
                      {...register("visibility")}
                    >
                      <MenuItem value="private">Private</MenuItem>
                      <MenuItem value="public">Public</MenuItem>
                    </TextField>
                    <Button
                      type="submit"
                      disabled={pending}
                      variant="contained"
                    >
                      Create collection
                    </Button>
                  </Stack>
                </Box>
              </CardContent>
            </Card>
          )}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: 2,
            }}
          >
            {list.data?.items.map((c) => (
              <Card variant="outlined" key={c.id}>
                <CardContent>
                  <Button onClick={() => setActiveId(c.id)}>{c.name}</Button>
                  <Typography>{c.description}</Typography>
                  <Chip size="small" label={c.visibility} />
                </CardContent>
              </Card>
            ))}
          </Box>
          {active.data && (
            <Card variant="outlined">
              <CardContent>
                <Stack spacing={2}>
                  <Typography variant="h6" component="h2">
                    {active.data.name}
                  </Typography>
                  {canEdit && owned && (
                    <Stack direction="row" spacing={2}>
                      <Button
                        disabled={
                          pending ||
                          !selected ||
                          active.data.items.some((o) => o.id === selected)
                        }
                        onClick={() =>
                          run(() =>
                            saveItems([
                              ...active.data!.items.map((o) => o.id),
                              selected,
                            ]),
                          )
                        }
                      >
                        Add selected object
                      </Button>
                      <Button
                        disabled={pending}
                        onClick={() =>
                          run(() =>
                            putJson(`/v1/collections/${activeId}`, {
                              name: active.data!.name,
                              description: active.data!.description,
                              visibility:
                                active.data!.visibility === "private"
                                  ? "public"
                                  : "private",
                            }),
                          )
                        }
                      >
                        Make{" "}
                        {active.data.visibility === "private"
                          ? "public"
                          : "private"}
                      </Button>
                      <Button
                        color="error"
                        disabled={pending}
                        onClick={() => {
                          if (
                            window.confirm(
                              "Delete this collection? Learning objects will be kept.",
                            )
                          )
                            run(async () => {
                              const result = await apiFetch(
                                `/v1/collections/${activeId}`,
                                { method: "DELETE" },
                              );
                              setActiveId("");
                              return result;
                            });
                        }}
                      >
                        Delete collection
                      </Button>
                    </Stack>
                  )}
                  {active.data.items.map((o, index, items) => (
                    <Stack
                      direction="row"
                      spacing={2}
                      key={o.id}
                      sx={{ alignItems: "center", flexWrap: "wrap" }}
                    >
                      <Link href={`/objects?id=${o.id}`}>{o.title}</Link>
                      <Chip size="small" label={o.status} />
                      {canEdit && owned && (
                        <>
                          <Button
                            disabled={pending || index === 0}
                            onClick={() =>
                              run(() => {
                                const ids = items.map((i) => i.id);
                                [ids[index - 1], ids[index]] = [
                                  ids[index],
                                  ids[index - 1],
                                ];
                                return saveItems(ids);
                              })
                            }
                          >
                            Move up
                          </Button>
                          <Button
                            disabled={pending}
                            onClick={() =>
                              run(() =>
                                saveItems(
                                  items
                                    .filter((i) => i.id !== o.id)
                                    .map((i) => i.id),
                                ),
                              )
                            }
                          >
                            Remove
                          </Button>
                        </>
                      )}
                    </Stack>
                  ))}
                  {!active.data.items.length && (
                    <Typography>
                      No accessible objects in this collection yet.
                    </Typography>
                  )}
                </Stack>
              </CardContent>
            </Card>
          )}
        </>
      )}
      {mode === "favorites" &&
        list.data?.items.map((o) => (
          <Card variant="outlined" key={o.id}>
            <CardContent>
              <Stack
                direction="row"
                spacing={2}
                sx={{ alignItems: "center", flexWrap: "wrap" }}
              >
                <Link href={`/objects?id=${o.id}`}>{o.title}</Link>
                <Chip size="small" label={o.status} />
                <Button
                  disabled={pending}
                  onClick={() => run(() => download(o.id))}
                >
                  Download
                </Button>
                <Button
                  disabled={pending}
                  onClick={() =>
                    run(() =>
                      apiFetch(`/v1/favorites/${o.id}`, { method: "DELETE" }),
                    )
                  }
                >
                  Remove favorite
                </Button>
              </Stack>
            </CardContent>
          </Card>
        ))}
      {mode === "versioning" && detail.data && (
        <Card variant="outlined">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h6" component="h2">
                {detail.data.title}
              </Typography>
              <Chip label={detail.data.status} />
              {detail.data.versions.map((v) => (
                <Stack
                  key={v.version_number}
                  direction="row"
                  spacing={2}
                  sx={{ alignItems: "center", flexWrap: "wrap" }}
                >
                  <Typography>
                    Version {v.version_number} · {v.original_filename} ·{" "}
                    {v.size_bytes.toLocaleString()} bytes
                  </Typography>
                  <Button
                    disabled={pending}
                    onClick={() =>
                      run(() => download(selected, v.version_number))
                    }
                  >
                    Download version
                  </Button>
                  {canEdit && (
                    <Button
                      disabled={pending}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Restore version ${v.version_number} as a new draft?`,
                          )
                        )
                          run(() =>
                            postJson(
                              `/v1/content/${selected}/versions/${v.version_number}/restore`,
                              {},
                            ),
                          );
                      }}
                    >
                      Restore file
                    </Button>
                  )}
                </Stack>
              ))}
            </Stack>
          </CardContent>
        </Card>
      )}
      {mode !== "versioning" && (
        <Stack
          direction="row"
          spacing={2}
          sx={{ alignItems: "center", flexWrap: "wrap" }}
        >
          <Button
            disabled={page === 1 || pending}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </Button>
          <Typography>
            Page {page} · {list.data?.total || 0} results
          </Typography>
          <Button
            disabled={page * 20 >= (list.data?.total || 0) || pending}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
          {list.data?.total === 0 && (
            <Typography>No matching {mode} yet.</Typography>
          )}
        </Stack>
      )}
    </Stack>
  );
}
