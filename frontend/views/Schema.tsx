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
import { apiBlob, apiFetch, ApiError, postJson, putJson } from "@/lib/api";

type CustomField = {
  id: number;
  key: string;
  label: string;
  field_type: "text" | "number" | "date" | "boolean" | "select";
  options: string[];
  vocabulary: string | null;
  required: boolean;
  active: boolean;
  help_text: string;
};
type Schema = {
  lom_fields: string[];
  controlled_lom_fields: string[];
  custom_fields: CustomField[];
  standards: { id: string; name: string }[];
};
type Vocab = { name: string; locked: boolean; active_terms: number };
type Summary = {
  items: number;
  average_score: number | null;
  below_threshold: number;
  weakest: { id: string; title: string; score: number; issues: string[] }[];
};
type Result = { id: string; ok: boolean; message?: string };

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong";
}

export default function SchemaPage() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const schema = useQuery({ queryKey: ["schema"], queryFn: () => apiFetch<Schema>("/v1/metadata/schema") });
  const vocabs = useQuery({
    queryKey: ["vocabularies"],
    queryFn: () => apiFetch<{ items: Vocab[] }>("/v1/taxonomy/vocabularies"),
  });
  const summary = useQuery({
    queryKey: ["quality-summary"],
    queryFn: () => apiFetch<Summary>("/v1/metadata/quality/summary"),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["schema"] });
    void queryClient.invalidateQueries({ queryKey: ["quality-summary"] });
  };
  const toggle = useMutation({
    mutationFn: (field: CustomField) =>
      putJson(`/v1/metadata/schema/fields/${field.id}`, { active: !field.active }),
    onSuccess: refresh,
    onError: (error) => setMessage(errorText(error)),
  });

  return (
    <Stack spacing={3}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Metadata schema
      </Typography>
      {message && <Alert severity="info" onClose={() => setMessage(null)}>{message}</Alert>}

      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>Standard fields</Typography>
        <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
          {(schema.data?.lom_fields ?? []).map((f) => (
            <Chip key={f} size="small" label={f} variant={schema.data?.controlled_lom_fields.includes(f) ? "filled" : "outlined"} />
          ))}
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Filled chips are controlled: when a locked vocabulary of the same name exists, only its terms are accepted.
        </Typography>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>Custom fields</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Label</TableCell>
              <TableCell>Key</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Values</TableCell>
              <TableCell>Required</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right" />
            </TableRow>
          </TableHead>
          <TableBody>
            {(schema.data?.custom_fields ?? []).map((f) => (
              <TableRow key={f.id}>
                <TableCell>{f.label}</TableCell>
                <TableCell><code>{f.key}</code></TableCell>
                <TableCell>{f.field_type}</TableCell>
                <TableCell>{f.vocabulary ? `vocabulary: ${f.vocabulary}` : f.options.join(", ") || "—"}</TableCell>
                <TableCell>{f.required ? "Yes" : "No"}</TableCell>
                <TableCell>{f.active ? "Active" : "Retired"}</TableCell>
                <TableCell align="right">
                  <Button size="small" onClick={() => toggle.mutate(f)}>{f.active ? "Retire" : "Restore"}</Button>
                </TableCell>
              </TableRow>
            ))}
            {schema.data && schema.data.custom_fields.length === 0 && (
              <TableRow>
                <TableCell colSpan={7}><Typography color="text.secondary">No custom fields yet.</Typography></TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <NewField vocabularies={vocabs.data?.items ?? []} onDone={() => { refresh(); setMessage("Field added."); }} onError={(m) => setMessage(m)} />
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>Quality</Typography>
        {summary.data && (
          <Stack spacing={1}>
            <Typography>
              {summary.data.items} readable items · average score {summary.data.average_score ?? "—"} ·{" "}
              {summary.data.below_threshold} below 60
            </Typography>
            {summary.data.weakest.slice(0, 5).map((w) => (
              <Typography key={w.id} variant="body2">
                {w.title} — {w.score}/100 {w.issues.length > 0 && `· ${w.issues[0]}`}
              </Typography>
            ))}
          </Stack>
        )}
        <CrosswalkPanel standards={schema.data?.standards ?? []} onError={setMessage} />
      </Paper>

      <BulkPanel onDone={(text) => { refresh(); setMessage(text); }} onError={setMessage} />
      <ImportExportPanel onDone={(text) => { refresh(); setMessage(text); }} onError={setMessage} />
    </Stack>
  );
}

function NewField({ vocabularies, onDone, onError }: {
  vocabularies: Vocab[];
  onDone: () => void;
  onError: (m: string) => void;
}) {
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [type, setType] = useState<CustomField["field_type"]>("text");
  const [options, setOptions] = useState("");
  const [vocabulary, setVocabulary] = useState("");
  const [required, setRequired] = useState(false);
  const create = useMutation({
    mutationFn: () =>
      postJson("/v1/metadata/schema/fields", {
        key,
        label,
        field_type: type,
        options: options.split(",").map((o) => o.trim()).filter(Boolean),
        vocabulary: vocabulary || null,
        required,
      }),
    onSuccess: () => {
      setKey(""); setLabel(""); setOptions(""); setVocabulary(""); setRequired(false);
      onDone();
    },
    onError: (error) => onError(errorText(error)),
  });
  return (
    <Stack spacing={2} sx={{ mt: 2, maxWidth: 640 }}>
      <Typography sx={{ fontWeight: 600 }}>Add a field</Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <TextField size="small" label="Key (a–z, 0–9, _)" value={key} onChange={(e) => setKey(e.target.value)} />
        <TextField size="small" label="Label" value={label} onChange={(e) => setLabel(e.target.value)} />
        <TextField select size="small" label="Type" value={type} onChange={(e) => setType(e.target.value as CustomField["field_type"])} sx={{ minWidth: 140 }}>
          {["text", "number", "date", "boolean", "select"].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
        </TextField>
      </Stack>
      {type === "select" && (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField size="small" label="Options (comma separated)" value={options} onChange={(e) => setOptions(e.target.value)} fullWidth />
          <TextField select size="small" label="Or a vocabulary" value={vocabulary} onChange={(e) => setVocabulary(e.target.value)} sx={{ minWidth: 200 }}>
            <MenuItem value="">None</MenuItem>
            {vocabularies.map((v) => <MenuItem key={v.name} value={v.name}>{v.name}</MenuItem>)}
          </TextField>
        </Stack>
      )}
      <FormControlLabel control={<Checkbox checked={required} onChange={(e) => setRequired(e.target.checked)} />} label="Required" />
      <Button variant="contained" sx={{ alignSelf: "flex-start" }} disabled={!key || !label || create.isPending} onClick={() => create.mutate()}>
        Add field
      </Button>
    </Stack>
  );
}

function CrosswalkPanel({ standards, onError }: { standards: { id: string; name: string }[]; onError: (m: string) => void }) {
  const [id, setId] = useState("");
  const [standard, setStandard] = useState("dublin-core");
  const [output, setOutput] = useState<string | null>(null);
  return (
    <Stack spacing={1} sx={{ mt: 2 }}>
      <Typography sx={{ fontWeight: 600 }}>Standards mapping</Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <TextField size="small" label="Item id" value={id} onChange={(e) => setId(e.target.value)} fullWidth />
        <TextField select size="small" label="Standard" value={standard} onChange={(e) => setStandard(e.target.value)} sx={{ minWidth: 220 }}>
          {standards.map((s) => <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>)}
        </TextField>
        <Button
          onClick={async () => {
            try {
              const result = await apiFetch(`/v1/metadata/${id.trim()}/crosswalk?standard=${standard}`);
              setOutput(JSON.stringify(result, null, 2));
            } catch (error) {
              onError(errorText(error));
            }
          }}
          disabled={!id.trim()}
        >
          Map
        </Button>
      </Stack>
      {output && <Paper variant="outlined" sx={{ p: 1, whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: 12 }}>{output}</Paper>}
    </Stack>
  );
}

function BulkPanel({ onDone, onError }: { onDone: (m: string) => void; onError: (m: string) => void }) {
  const [ids, setIds] = useState("");
  const [subject, setSubject] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [add, setAdd] = useState("");
  const [remove, setRemove] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const split = (text: string, sep: RegExp) => text.split(sep).map((x) => x.trim()).filter(Boolean);
  const run = useMutation({
    mutationFn: () =>
      postJson<{ results: Result[]; succeeded: number }>("/v1/metadata/bulk-update", {
        ids: split(ids, /[\s,]+/),
        changes: {
          subject: subject || undefined,
          learning_resource_type: resourceType || undefined,
          add_keywords: split(add, /,/),
          remove_keywords: split(remove, /,/),
        },
      }),
    onSuccess: (data) => {
      setResults(data.results);
      onDone(`Bulk update: ${data.succeeded} of ${data.results.length} items changed.`);
    },
    onError: (error) => onError(errorText(error)),
  });
  return (
    <Paper sx={{ p: 2 }}>
      <Typography sx={{ fontWeight: 600, mb: 1 }}>Bulk update</Typography>
      <Stack spacing={2}>
        <TextField size="small" multiline minRows={2} label="Item ids (space or comma separated, up to 200)" value={ids} onChange={(e) => setIds(e.target.value)} />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField size="small" label="Set subject" value={subject} onChange={(e) => setSubject(e.target.value)} fullWidth />
          <TextField size="small" label="Set resource type" value={resourceType} onChange={(e) => setResourceType(e.target.value)} fullWidth />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField size="small" label="Add keywords (comma separated)" value={add} onChange={(e) => setAdd(e.target.value)} fullWidth />
          <TextField size="small" label="Remove keywords (comma separated)" value={remove} onChange={(e) => setRemove(e.target.value)} fullWidth />
        </Stack>
        <Button variant="contained" sx={{ alignSelf: "flex-start" }} disabled={!ids.trim() || run.isPending} onClick={() => run.mutate()}>
          Apply to items
        </Button>
        {results.filter((r) => !r.ok).map((r) => (
          <Typography key={r.id} variant="body2" color="error">{r.id}: {r.message}</Typography>
        ))}
      </Stack>
    </Paper>
  );
}

function ImportExportPanel({ onDone, onError }: { onDone: (m: string) => void; onError: (m: string) => void }) {
  const [csv, setCsv] = useState("");
  const [preview, setPreview] = useState<{ succeeded: number; rows: number; results: Result[] } | null>(null);
  const runImport = useMutation({
    mutationFn: (dryRun: boolean) => postJson<{ succeeded: number; rows: number; results: Result[] }>(
      "/v1/metadata/import", { content: csv, dry_run: dryRun }),
    onSuccess: (data, dryRun) => {
      if (dryRun) {
        setPreview(data);
      } else {
        setPreview(null);
        onDone(`Imported ${data.succeeded} of ${data.rows} rows.`);
      }
    },
    onError: (error) => onError(errorText(error)),
  });
  async function download() {
    try {
      const blob = await apiBlob("/v1/metadata/export?format=csv");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "metadata-export.csv";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (error) {
      onError(errorText(error));
    }
  }
  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 1 }}>
        <Typography sx={{ fontWeight: 600 }}>Import and export</Typography>
        <Button size="small" onClick={download}>Export CSV</Button>
      </Stack>
      <Stack spacing={2}>
        <TextField size="small" multiline minRows={4} label="CSV with an id column (paste or load a file)" value={csv} onChange={(e) => { setCsv(e.target.value); setPreview(null); }} />
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" disabled={!csv.trim() || runImport.isPending} onClick={() => runImport.mutate(true)}>Check first</Button>
          <Button variant="contained" disabled={!csv.trim() || !preview || preview.succeeded !== preview.rows || runImport.isPending} onClick={() => runImport.mutate(false)}>
            Import
          </Button>
        </Stack>
        {preview && (
          <Stack spacing={0.5}>
            <Typography variant="body2">Check: {preview.succeeded} of {preview.rows} rows are valid. Nothing has changed yet.</Typography>
            {preview.results.filter((r) => !r.ok).map((r) => (
              <Typography key={r.id} variant="body2" color="error">{r.id || "row"}: {r.message}</Typography>
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
