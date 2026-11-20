"use client";

import { useState } from "react";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { ApiError, apiBlob, apiFetch, postJson, putJson } from "@/lib/api";

type Branding = { app_name: string; tagline: string; primary_color: string; logo_url: string; footer_text: string };
type Hook = { id: number; name: string; url: string; events: string[]; active: boolean };
type Delivery = { id: number; webhook_id: number; event: string; status: string; attempts: number; response_code: number | null; last_error: string | null; created_at: string };
type Overview = Record<string, number>;

const EVENTS = [
  "content.create", "content.quarantine", "metadata.update", "workflow.submitted", "workflow.approved",
  "workflow.rejected", "workflow.published", "version.restore", "collection.publish", "ai.accepted",
];

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong";
}

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ name: string; secret: string } | null>(null);
  const overview = useQuery({ queryKey: ["admin-overview"], queryFn: () => apiFetch<Overview>("/v1/admin/overview") });
  const branding = useQuery({ queryKey: ["branding"], queryFn: () => apiFetch<Branding>("/v1/branding") });
  const hooks = useQuery({ queryKey: ["webhooks"], queryFn: () => apiFetch<{ items: Hook[] }>("/v1/integrations/webhooks") });
  const deliveries = useQuery({
    queryKey: ["deliveries"],
    queryFn: () => apiFetch<{ items: Delivery[] }>("/v1/integrations/deliveries"),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    void queryClient.invalidateQueries({ queryKey: ["deliveries"] });
    void queryClient.invalidateQueries({ queryKey: ["admin-overview"] });
  };
  const fail = (error: unknown) => setMessage(errorText(error));

  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>Administration and integrations</Typography>
      {message && <Alert severity="info" onClose={() => setMessage(null)}>{message}</Alert>}

      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>Overview</Typography>
        <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
          {Object.entries(overview.data ?? {}).map(([k, v]) => (
            <Chip key={k} label={`${k.replace(/_/g, " ")}: ${v}`} />
          ))}
        </Stack>
      </Paper>

      <BrandingForm current={branding.data} onSaved={() => { void queryClient.invalidateQueries({ queryKey: ["branding"] }); setMessage("Branding saved."); }} onError={fail} />

      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>Webhooks</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell><TableCell>Endpoint</TableCell><TableCell>Events</TableCell>
              <TableCell>Status</TableCell><TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(hooks.data?.items ?? []).map((h) => (
              <TableRow key={h.id}>
                <TableCell>{h.name}</TableCell>
                <TableCell><code>{h.url}</code></TableCell>
                <TableCell>{h.events.join(", ")}</TableCell>
                <TableCell>{h.active ? "Active" : "Paused"}</TableCell>
                <TableCell align="right">
                  <Button size="small" onClick={() => postJson(`/v1/integrations/webhooks/${h.id}/test`, {}).then(() => { refresh(); setMessage("Test event queued. Dispatch deliveries to send it."); }).catch(fail)}>Test</Button>
                  <Button size="small" onClick={() => putJson(`/v1/integrations/webhooks/${h.id}`, { active: !h.active }).then(refresh).catch(fail)}>{h.active ? "Pause" : "Resume"}</Button>
                  <Button size="small" color="error" onClick={() => { if (window.confirm("Delete this webhook?")) apiFetch(`/v1/integrations/webhooks/${h.id}`, { method: "DELETE" }).then(refresh).catch(fail); }}>Delete</Button>
                </TableCell>
              </TableRow>
            ))}
            {hooks.data && hooks.data.items.length === 0 && (
              <TableRow><TableCell colSpan={5}><Typography color="text.secondary">No webhooks yet.</Typography></TableCell></TableRow>
            )}
          </TableBody>
        </Table>
        <NewWebhook onCreated={(name, value) => { setSecret({ name, secret: value }); refresh(); }} onError={fail} />
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Stack direction="row" spacing={1} sx={{ justifyContent: "space-between", alignItems: "center", mb: 1 }}>
          <Typography sx={{ fontWeight: 600 }}>Recent deliveries</Typography>
          <Button size="small" onClick={() => postJson<{ delivered: number; failed: number }>("/v1/integrations/deliveries/dispatch", {})
            .then((r) => { refresh(); setMessage(`Dispatched: ${r.delivered} delivered, ${r.failed} failed.`); }).catch(fail)}>
            Send pending
          </Button>
        </Stack>
        <Table size="small">
          <TableHead>
            <TableRow><TableCell>Event</TableCell><TableCell>Status</TableCell><TableCell>Attempts</TableCell><TableCell>Response</TableCell><TableCell>Last error</TableCell></TableRow>
          </TableHead>
          <TableBody>
            {(deliveries.data?.items ?? []).map((d) => (
              <TableRow key={d.id}>
                <TableCell>{d.event}</TableCell>
                <TableCell>{d.status}</TableCell>
                <TableCell>{d.attempts}</TableCell>
                <TableCell>{d.response_code ?? "—"}</TableCell>
                <TableCell>{d.last_error ?? ""}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <BundlePanel onError={fail} onDone={(text) => { setMessage(text); refresh(); }} />

      <Dialog open={!!secret} onClose={() => setSecret(null)} fullWidth maxWidth="sm">
        <DialogTitle>Signing secret for {secret?.name}</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>Copy this now. It is shown only once. Use it to verify the X-ELOR-Signature header (HMAC-SHA256 over “timestamp.body”).</Alert>
          <Paper variant="outlined" sx={{ p: 1, fontFamily: "monospace", wordBreak: "break-all" }}>{secret?.secret}</Paper>
        </DialogContent>
        <DialogActions><Button onClick={() => setSecret(null)}>I have copied it</Button></DialogActions>
      </Dialog>
    </Stack>
  );
}

function BrandingForm({ current, onSaved, onError }: {
  current: Branding | undefined;
  onSaved: () => void;
  onError: (e: unknown) => void;
}) {
  const [draft, setDraft] = useState<Partial<Branding>>({});
  const value = (key: keyof Branding) => (draft[key] ?? current?.[key] ?? "") as string;
  const save = useMutation({
    mutationFn: () => putJson("/v1/branding", draft),
    onSuccess: () => { setDraft({}); onSaved(); },
    onError,
  });
  return (
    <Paper sx={{ p: 2 }}>
      <Typography sx={{ fontWeight: 600, mb: 1 }}>Branding</Typography>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ flexWrap: "wrap", gap: 2 }}>
        <TextField size="small" label="Application name" value={value("app_name")} onChange={(e) => setDraft({ ...draft, app_name: e.target.value })} />
        <TextField size="small" label="Tagline" value={value("tagline")} onChange={(e) => setDraft({ ...draft, tagline: e.target.value })} sx={{ minWidth: 300 }} />
        <TextField size="small" label="Primary colour (#rrggbb)" value={value("primary_color")} onChange={(e) => setDraft({ ...draft, primary_color: e.target.value })} />
        <TextField size="small" label="Logo URL (https)" value={value("logo_url")} onChange={(e) => setDraft({ ...draft, logo_url: e.target.value })} sx={{ minWidth: 260 }} />
        <TextField size="small" label="Footer text" value={value("footer_text")} onChange={(e) => setDraft({ ...draft, footer_text: e.target.value })} sx={{ minWidth: 260 }} />
        <Button variant="contained" disabled={Object.keys(draft).length === 0 || save.isPending} onClick={() => save.mutate()}>Save branding</Button>
      </Stack>
    </Paper>
  );
}

function NewWebhook({ onCreated, onError }: { onCreated: (name: string, secret: string) => void; onError: (e: unknown) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["workflow.published"]);
  const create = useMutation({
    mutationFn: () => postJson<{ name: string; secret: string }>("/v1/integrations/webhooks", { name, url, events }),
    onSuccess: (r) => { onCreated(r.name, r.secret); setName(""); setUrl(""); },
    onError,
  });
  return (
    <Stack spacing={2} sx={{ mt: 2 }}>
      <Typography sx={{ fontWeight: 600 }}>Add a webhook</Typography>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <TextField size="small" label="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <TextField size="small" label="Endpoint (https)" value={url} onChange={(e) => setUrl(e.target.value)} fullWidth />
      </Stack>
      <TextField select size="small" slotProps={{ select: { multiple: true } }} label="Events" value={events} onChange={(e) => setEvents(typeof e.target.value === "string" ? e.target.value.split(",") : e.target.value)}>
        {EVENTS.map((ev) => <MenuItem key={ev} value={ev}>{ev}</MenuItem>)}
      </TextField>
      <Button variant="outlined" sx={{ alignSelf: "flex-start" }} disabled={!name || !url || events.length === 0 || create.isPending} onClick={() => create.mutate()}>
        Create webhook
      </Button>
    </Stack>
  );
}

function BundlePanel({ onDone, onError }: { onDone: (text: string) => void; onError: (e: unknown) => void }) {
  const [id, setId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  async function exportBundle() {
    try {
      const blob = await apiBlob(`/v1/interop/${id.trim()}/bundle`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `elor-${id.trim()}.zip`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (error) {
      onError(error);
    }
  }
  return (
    <Paper sx={{ p: 2 }}>
      <Typography sx={{ fontWeight: 600, mb: 1 }}>Content bundles</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        A bundle holds the package, LOM metadata, a Dublin Core rendering and an xAPI activity definition.
      </Typography>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: { md: "center" }, flexWrap: "wrap", gap: 2 }}>
        <TextField size="small" label="Item id to export" value={id} onChange={(e) => setId(e.target.value)} sx={{ minWidth: 300 }} />
        <Button variant="outlined" disabled={!id.trim()} onClick={exportBundle}>Export bundle</Button>
        <Button component="label" variant="outlined">
          {file ? file.name : "Choose bundle to import"}
          <input hidden type="file" accept=".zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Button>
        <Button
          variant="contained"
          disabled={!file}
          onClick={async () => {
            if (!file) return;
            const form = new FormData();
            form.append("bundle", file);
            try {
              const result = await apiFetch<{ id: string; title: string; warnings: string[] }>(
                "/v1/interop/import", { method: "POST", body: form });
              setFile(null);
              onDone(`Imported “${result.title}” as a draft.${result.warnings.length ? " Warnings: " + result.warnings.join("; ") : ""}`);
            } catch (error) {
              onError(error);
            }
          }}
        >
          Import
        </Button>
      </Stack>
    </Paper>
  );
}
