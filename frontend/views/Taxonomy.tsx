"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
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

type Vocab = { id: number; name: string; description: string; locked: boolean; active_terms: number };
type Term = {
  id: number;
  code: string;
  label: string;
  status: "active" | "deprecated" | "merged";
  parent_id: number | null;
  merged_into_id: number | null;
};

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong";
}

export default function TaxonomyPage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const vocabs = useQuery({
    queryKey: ["vocabularies"],
    queryFn: () => apiFetch<{ items: Vocab[] }>("/v1/taxonomy/vocabularies"),
  });
  const terms = useQuery({
    queryKey: ["terms", selected],
    queryFn: () => apiFetch<{ items: Term[] }>(`/v1/taxonomy/vocabularies/${selected}/terms`),
    enabled: !!selected,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["vocabularies"] });
    void queryClient.invalidateQueries({ queryKey: ["terms", selected] });
  };
  const fail = (error: unknown) => setMessage(errorText(error));
  const current = vocabs.data?.items.find((v) => v.name === selected);

  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Taxonomy
      </Typography>
      {message && <Alert severity="info" onClose={() => setMessage(null)}>{message}</Alert>}

      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>Vocabularies</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Description</TableCell>
              <TableCell>Active terms</TableCell>
              <TableCell>Enforced</TableCell>
              <TableCell align="right" />
            </TableRow>
          </TableHead>
          <TableBody>
            {(vocabs.data?.items ?? []).map((v) => (
              <TableRow key={v.id} selected={v.name === selected} hover onClick={() => setSelected(v.name)} sx={{ cursor: "pointer" }}>
                <TableCell><code>{v.name}</code></TableCell>
                <TableCell>{v.description}</TableCell>
                <TableCell>{v.active_terms}</TableCell>
                <TableCell>{v.locked ? <Chip size="small" label="Locked" /> : "Suggested"}</TableCell>
                <TableCell align="right">
                  <Button
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      putJson(`/v1/taxonomy/vocabularies/${v.name}`, { locked: !v.locked })
                        .then(() => refresh())
                        .catch(fail);
                    }}
                  >
                    {v.locked ? "Unlock" : "Lock"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <NewVocabulary onDone={() => { refresh(); setMessage("Vocabulary created."); }} onError={fail} />
      </Paper>

      {current && (
        <Paper sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} sx={{ justifyContent: "space-between", alignItems: "center", mb: 1, flexWrap: "wrap", gap: 1 }}>
            <Typography sx={{ fontWeight: 600 }}>Terms in {current.name}</Typography>
            <Stack direction="row" spacing={1}>
              <Button size="small" onClick={async () => {
                try {
                  const blob = await apiBlob(`/v1/taxonomy/vocabularies/${current.name}/export`);
                  const url = URL.createObjectURL(blob);
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = `${current.name}-terms.csv`;
                  link.click();
                  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
                } catch (error) {
                  fail(error);
                }
              }}>Export CSV</Button>
            </Stack>
          </Stack>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Code</TableCell>
                <TableCell>Label</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(terms.data?.items ?? []).map((t) => (
                <TermRow key={t.id} term={t} terms={terms.data?.items ?? []} onChanged={refresh} onError={fail} />
              ))}
              {terms.data && terms.data.items.length === 0 && (
                <TableRow><TableCell colSpan={4}><Typography color="text.secondary">No terms yet.</Typography></TableCell></TableRow>
              )}
            </TableBody>
          </Table>
          <NewTerm vocabulary={current.name} terms={terms.data?.items ?? []} onDone={() => { refresh(); setMessage("Term added."); }} onError={fail} />
          <TermImport vocabulary={current.name} onDone={(text) => { refresh(); setMessage(text); }} onError={fail} />
        </Paper>
      )}
    </Stack>
  );
}

function TermRow({ term, terms, onChanged, onError }: {
  term: Term;
  terms: Term[];
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const [target, setTarget] = useState("");
  const [label, setLabel] = useState(term.label);
  const merge = useMutation({
    mutationFn: () => postJson<{ items_updated: number; items_skipped: number; children_moved: number }>(
      `/v1/taxonomy/terms/${term.id}/merge`, { into_id: Number(target) }),
    onSuccess: (r) => {
      onChanged();
      alert(`Merged. ${r.items_updated} item(s) updated, ${r.items_skipped} locked item(s) skipped, ${r.children_moved} child term(s) moved.`);
    },
    onError,
  });
  const save = useMutation({
    mutationFn: (patch: { label?: string; status?: Term["status"] }) => putJson(`/v1/taxonomy/terms/${term.id}`, patch),
    onSuccess: onChanged,
    onError,
  });
  const merged = term.status === "merged";
  const candidates = terms.filter((t) => t.id !== term.id && t.status === "active");
  return (
    <TableRow>
      <TableCell><code>{term.code}</code></TableCell>
      <TableCell>
        <TextField
          size="small"
          variant="standard"
          value={label}
          disabled={merged}
          onChange={(e) => setLabel(e.target.value)}
          onBlur={() => { if (label !== term.label && label.trim()) save.mutate({ label }); }}
        />
      </TableCell>
      <TableCell>
        {merged ? <Chip size="small" label={`Merged into #${term.merged_into_id}`} /> : (
          <FormControlLabel
            control={<Checkbox size="small" checked={term.status === "active"} onChange={(e) => save.mutate({ status: e.target.checked ? "active" : "deprecated" })} />}
            label={term.status === "active" ? "Active" : "Deprecated"}
          />
        )}
      </TableCell>
      <TableCell>
        {!merged && candidates.length > 0 && (
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <TextField select size="small" label="Merge into" value={target} onChange={(e) => setTarget(e.target.value)} sx={{ minWidth: 200 }}>
              {candidates.map((c) => <MenuItem key={c.id} value={String(c.id)}>{c.label}</MenuItem>)}
            </TextField>
            <Button size="small" disabled={!target || merge.isPending} onClick={() => {
              if (window.confirm(`Merge “${term.label}” into the selected term? Editable items are updated; locked items are skipped.`)) merge.mutate();
            }}>Merge</Button>
          </Stack>
        )}
      </TableCell>
    </TableRow>
  );
}

function NewVocabulary({ onDone, onError }: { onDone: () => void; onError: (e: unknown) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [locked, setLocked] = useState(false);
  const create = useMutation({
    mutationFn: () => postJson("/v1/taxonomy/vocabularies", { name, description, locked }),
    onSuccess: () => { setName(""); setDescription(""); setLocked(false); onDone(); },
    onError,
  });
  return (
    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 2, alignItems: { sm: "center" } }}>
      <TextField size="small" label="Name (e.g. subject)" value={name} onChange={(e) => setName(e.target.value)} />
      <TextField size="small" label="Description" value={description} onChange={(e) => setDescription(e.target.value)} fullWidth />
      <FormControlLabel control={<Checkbox checked={locked} onChange={(e) => setLocked(e.target.checked)} />} label="Locked" />
      <Button variant="contained" disabled={!name || create.isPending} onClick={() => create.mutate()}>Create</Button>
    </Stack>
  );
}

function NewTerm({ vocabulary, terms, onDone, onError }: {
  vocabulary: string;
  terms: Term[];
  onDone: () => void;
  onError: (e: unknown) => void;
}) {
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [parent, setParent] = useState("");
  const create = useMutation({
    mutationFn: () => postJson(`/v1/taxonomy/vocabularies/${vocabulary}/terms`, {
      code, label, parent_code: parent || null,
    }),
    onSuccess: () => { setCode(""); setLabel(""); setParent(""); onDone(); },
    onError,
  });
  return (
    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 2, alignItems: { sm: "center" } }}>
      <TextField size="small" label="Code" value={code} onChange={(e) => setCode(e.target.value)} />
      <TextField size="small" label="Label" value={label} onChange={(e) => setLabel(e.target.value)} fullWidth />
      <TextField select size="small" label="Parent" value={parent} onChange={(e) => setParent(e.target.value)} sx={{ minWidth: 180 }}>
        <MenuItem value="">None</MenuItem>
        {terms.filter((t) => t.status === "active").map((t) => <MenuItem key={t.id} value={t.code}>{t.label}</MenuItem>)}
      </TextField>
      <Button variant="contained" disabled={!code || !label || create.isPending} onClick={() => create.mutate()}>Add term</Button>
    </Stack>
  );
}

function TermImport({ vocabulary, onDone, onError }: {
  vocabulary: string;
  onDone: (text: string) => void;
  onError: (e: unknown) => void;
}) {
  const [csv, setCsv] = useState("");
  const run = useMutation({
    mutationFn: () => postJson<{ created: number; updated: number }>(
      `/v1/taxonomy/vocabularies/${vocabulary}/import`, { content: csv, dry_run: false }),
    onSuccess: (r) => { setCsv(""); onDone(`Terms imported: ${r.created} created, ${r.updated} updated.`); },
    onError,
  });
  return (
    <Stack spacing={1} sx={{ mt: 2 }}>
      <TextField size="small" multiline minRows={3} label="Import CSV: code,label,parent_code" value={csv} onChange={(e) => setCsv(e.target.value)} />
      <Button sx={{ alignSelf: "flex-start" }} disabled={!csv.trim() || run.isPending} onClick={() => run.mutate()}>Import terms</Button>
    </Stack>
  );
}
