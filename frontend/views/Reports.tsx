"use client";

import { useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
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
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AgentStream } from "@/components/AgentStream";
import { ApiError, apiBlob, apiFetch, postJson, putJson } from "@/lib/api";

type Chart = {
  type: "line" | "bar";
  drill: string | null;
  keys: string[];
  points: { x: string; values: number[] }[];
} | null;
type Report = {
  key: string;
  title: string;
  columns: string[];
  rows: (string | number | null)[][];
  row_count: number;
  summary: Record<string, unknown>;
  chart: Chart;
};
type Filters = { start: string; end: string; subject: string; status: string; kind: string; department: string };
type Schedule = {
  id: number;
  name: string;
  report: string;
  format: string;
  window_days: number;
  cadence: string;
  recipients: string[];
  active: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
};
type Run = { id: number; filename: string; report: string; format: string; rows: number; created_at: string };

const REPORTS = [
  ["usage", "Usage"], ["reuse", "Reuse"], ["growth", "Growth"], ["workflow", "Workflow"],
  ["storage", "Storage"], ["departments", "Departments"],
] as const;
const FORMATS = ["csv", "xlsx", "pdf"] as const;
const PALETTE = ["#1762c4", "#0f8a5f", "#c77700", "#8a3ffc", "#d6336c"];

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong";
}

function query(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  if (filters.subject) params.set("subject", filters.subject);
  if (filters.status) params.set("status", filters.status);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.department) params.set("department_id", filters.department);
  return params.toString();
}

async function download(path: string, filename: string) {
  const blob = await apiBlob(path);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export default function ReportsPage() {
  const [tab, setTab] = useState<string>("usage");
  const [filters, setFilters] = useState<Filters>({ start: "", end: "", subject: "", status: "", kind: "", department: "" });
  const [message, setMessage] = useState<string | null>(null);
  const [drill, setDrill] = useState<{ title: string; items: { id: string; title: string; status: string }[] } | null>(null);
  const qs = query(filters);
  const report = useQuery({
    queryKey: ["report", tab, qs],
    queryFn: () => apiFetch<Report>(`/v1/analytics/reports/${tab}?${qs}`),
  });
  const completions = useQuery({
    queryKey: ["completions"],
    queryFn: () => apiFetch<{ total_completions: number; unique_learners: number }>("/v1/reports/completions"),
    retry: false,
  });

  async function openDrill(dimension: string, value: string, label: string, rowKey?: string) {
    try {
      const data = await apiFetch<{ items: { id: string; title: string; status: string }[] }>(
        `/v1/analytics/drill?dimension=${dimension}&value=${encodeURIComponent(rowKey ?? value)}&${qs}`,
      );
      setDrill({ title: `${label}: ${data.items.length} item(s)`, items: data.items });
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  const chartData = useMemo(() => {
    const chart = report.data?.chart;
    if (!chart) return [];
    return chart.points.map((p) => {
      const row: Record<string, string | number> = { x: p.x };
      chart.keys.forEach((k, i) => { row[k] = p.values[i] ?? 0; });
      return row;
    });
  }, [report.data]);

  const chart = report.data?.chart ?? null;
  const exportName = tab;
  const summaryEntries = Object.entries(report.data?.summary ?? {}).filter(([, v]) => typeof v !== "object" || v === null);

  return (
    <Stack spacing={3}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap", gap: 1, justifyContent: "space-between" }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>Reports and analytics</Typography>
        <Stack direction="row" spacing={1}>
          {FORMATS.map((f) => (
            <Button key={f} variant="outlined" size="small" onClick={() =>
              download(`/v1/analytics/reports/${exportName}/export?format=${f}&${qs}`, `${exportName}-report.${f}`)
                .catch((e) => setMessage(errorText(e)))}>
              Export {f.toUpperCase()}
            </Button>
          ))}
        </Stack>
      </Stack>
      {message && <Alert severity="error" onClose={() => setMessage(null)}>{message}</Alert>}

      <Paper sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ flexWrap: "wrap", gap: 2 }}>
          <TextField size="small" type="date" label="From" slotProps={{ inputLabel: { shrink: true } }} value={filters.start} onChange={(e) => setFilters({ ...filters, start: e.target.value })} />
          <TextField size="small" type="date" label="To" slotProps={{ inputLabel: { shrink: true } }} value={filters.end} onChange={(e) => setFilters({ ...filters, end: e.target.value })} />
          <TextField size="small" label="Subject" value={filters.subject} onChange={(e) => setFilters({ ...filters, subject: e.target.value })} />
          <TextField select size="small" label="Status" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })} sx={{ minWidth: 150 }}>
            <MenuItem value="">Any</MenuItem>
            {["draft", "submitted", "under_review", "approved", "rejected", "published"].map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Type" value={filters.kind} onChange={(e) => setFilters({ ...filters, kind: e.target.value })} sx={{ minWidth: 130 }}>
            <MenuItem value="">Any</MenuItem>
            {["file", "rich_text", "quiz", "assessment"].map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Department id" value={filters.department} onChange={(e) => setFilters({ ...filters, department: e.target.value })} sx={{ maxWidth: 150 }} />
          <Button size="small" onClick={() => setFilters({ start: "", end: "", subject: "", status: "", kind: "", department: "" })}>Reset</Button>
        </Stack>
      </Paper>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable">
        {REPORTS.map(([key, label]) => <Tab key={key} value={key} label={label} />)}
        <Tab value="scheduled" label="Scheduled" />
        <Tab value="ask" label="Ask" />
      </Tabs>

      {tab === "scheduled" && <ScheduledPanel onError={setMessage} />}
      {tab === "ask" && (
        <Stack spacing={2}>
          <Typography color="text.secondary">Try: “How many completions do we have?” or “Completions by object”.</Typography>
          <AgentStream endpoint="/v1/agents/ask" buildBody={(question: string) => ({ question })} placeholder="Ask about completions" />
        </Stack>
      )}

      {REPORTS.some(([key]) => key === tab) && (
        <Stack spacing={2}>
          {report.isLoading && <Typography>Loading…</Typography>}
          {report.error && <Alert severity="error">{errorText(report.error)}</Alert>}
          {report.data && (
            <>
              <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", gap: 2 }}>
                {summaryEntries.map(([k, v]) => (
                  <Paper key={k} sx={{ p: 2, minWidth: 150 }}>
                    <Typography variant="body2" color="text.secondary">{k.replace(/_/g, " ")}</Typography>
                    <Typography variant="h6" sx={{ fontWeight: 700 }}>{v === null ? "—" : String(v)}</Typography>
                  </Paper>
                ))}
                {tab === "usage" && completions.data && (
                  <Paper sx={{ p: 2, minWidth: 150 }}>
                    <Typography variant="body2" color="text.secondary">xAPI completions</Typography>
                    <Typography variant="h6" sx={{ fontWeight: 700 }}>{completions.data.total_completions}</Typography>
                  </Paper>
                )}
              </Stack>

              {chart && chartData.length > 0 && (
                <Paper sx={{ p: 2, height: 320 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    {chart.type === "line" ? (
                      <LineChart data={chartData} onClick={(state) => {
                        const label = (state as { activeLabel?: string } | null)?.activeLabel;
                        if (chart.drill && label) openDrill(chart.drill, label, label);
                      }}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="x" />
                        <YAxis allowDecimals={false} />
                        <Tooltip />
                        <Legend />
                        {chart.keys.map((k, i) => <Line key={k} type="monotone" dataKey={k} stroke={PALETTE[i % PALETTE.length]} />)}
                      </LineChart>
                    ) : (
                      <BarChart data={chartData} onClick={(state) => {
                        const label = (state as { activeLabel?: string } | null)?.activeLabel;
                        if (!chart.drill || !label) return;
                        const row = report.data?.rows.find((r) => String(r[0]) === label);
                        openDrill(chart.drill, label, label, row ? String(row[1]) : undefined);
                      }}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="x" />
                        <YAxis allowDecimals={false} />
                        <Tooltip />
                        <Legend />
                        {chart.keys.map((k, i) => <Bar key={k} dataKey={k} fill={PALETTE[i % PALETTE.length]} />)}
                      </BarChart>
                    )}
                  </ResponsiveContainer>
                  {chart.drill && <Typography variant="caption" color="text.secondary">Click a point to see the items behind it.</Typography>}
                </Paper>
              )}

              {tab === "usage" && Array.isArray(report.data.summary.top_items) && (
                <Paper sx={{ p: 2 }}>
                  <Typography sx={{ fontWeight: 600, mb: 1 }}>Most downloaded</Typography>
                  {(report.data.summary.top_items as [string, string, number][]).map(([title, id, n]) => (
                    <Stack key={id} direction="row" spacing={1} sx={{ alignItems: "center" }}>
                      <Button component={RouterLink} to={`/objects?id=${id}`} size="small">{title}</Button>
                      <Chip size="small" label={`${n} downloads`} />
                    </Stack>
                  ))}
                </Paper>
              )}

              <Paper sx={{ p: 2, overflowX: "auto" }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>{report.data.columns.map((c) => <TableCell key={c}>{c}</TableCell>)}</TableRow>
                  </TableHead>
                  <TableBody>
                    {report.data.rows.map((row, i) => (
                      <TableRow key={i}>
                        {row.map((cell, j) => <TableCell key={j}>{cell === null ? "—" : String(cell)}</TableCell>)}
                      </TableRow>
                    ))}
                    {report.data.rows.length === 0 && (
                      <TableRow><TableCell colSpan={report.data.columns.length}><Typography color="text.secondary">No data for these filters.</Typography></TableCell></TableRow>
                    )}
                  </TableBody>
                </Table>
                {report.data.row_count > report.data.rows.length && (
                  <Typography variant="caption" color="text.secondary">Showing {report.data.rows.length} of {report.data.row_count} rows. Export for the full set.</Typography>
                )}
              </Paper>
            </>
          )}
        </Stack>
      )}

      <Dialog open={!!drill} onClose={() => setDrill(null)} fullWidth maxWidth="sm">
        <DialogTitle>{drill?.title}</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1}>
            {(drill?.items ?? []).map((i) => (
              <Stack key={i.id} direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Button component={RouterLink} to={`/objects?id=${i.id}`} size="small" onClick={() => setDrill(null)}>{i.title}</Button>
                <Chip size="small" label={i.status} />
              </Stack>
            ))}
            {drill && drill.items.length === 0 && <Typography color="text.secondary">Nothing here.</Typography>}
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setDrill(null)}>Close</Button></DialogActions>
      </Dialog>
    </Stack>
  );
}

function ScheduledPanel({ onError }: { onError: (m: string) => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [report, setReport] = useState("usage");
  const [format, setFormat] = useState<(typeof FORMATS)[number]>("csv");
  const [windowDays, setWindowDays] = useState("30");
  const [cadence, setCadence] = useState("weekly");
  const [recipients, setRecipients] = useState("");
  const schedules = useQuery({
    queryKey: ["schedules"],
    queryFn: () => apiFetch<{ items: Schedule[] }>("/v1/analytics/schedules"),
  });
  const runs = useQuery({
    queryKey: ["report-runs"],
    queryFn: () => apiFetch<{ items: Run[] }>("/v1/analytics/runs"),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["schedules"] });
    void queryClient.invalidateQueries({ queryKey: ["report-runs"] });
  };
  const create = useMutation({
    mutationFn: () => postJson("/v1/analytics/schedules", {
      name, report, format, window_days: Number(windowDays), cadence,
      recipients: recipients.split(/[\s,]+/).filter(Boolean),
    }),
    onSuccess: () => { setName(""); setRecipients(""); refresh(); },
    onError: (e) => onError(errorText(e)),
  });
  const runNow = useMutation({
    mutationFn: (id: number) => postJson(`/v1/analytics/schedules/${id}/run`, {}),
    onSuccess: refresh,
    onError: (e) => onError(errorText(e)),
  });
  const toggle = useMutation({
    mutationFn: (s: Schedule) => putJson(`/v1/analytics/schedules/${s.id}`, { active: !s.active }),
    onSuccess: refresh,
    onError: (e) => onError(errorText(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => apiFetch(`/v1/analytics/schedules/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: (e) => onError(errorText(e)),
  });

  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>New scheduled report</Typography>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ flexWrap: "wrap", gap: 2 }}>
          <TextField size="small" label="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField select size="small" label="Report" value={report} onChange={(e) => setReport(e.target.value)} sx={{ minWidth: 140 }}>
            {REPORTS.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Format" value={format} onChange={(e) => setFormat(e.target.value as (typeof FORMATS)[number])} sx={{ minWidth: 110 }}>
            {FORMATS.map((f) => <MenuItem key={f} value={f}>{f.toUpperCase()}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Repeat" value={cadence} onChange={(e) => setCadence(e.target.value)} sx={{ minWidth: 120 }}>
            <MenuItem value="daily">Daily</MenuItem>
            <MenuItem value="weekly">Weekly</MenuItem>
          </TextField>
          <TextField size="small" label="Window (days)" value={windowDays} onChange={(e) => setWindowDays(e.target.value)} sx={{ maxWidth: 140 }} />
          <TextField size="small" label="Also send to (user ids)" value={recipients} onChange={(e) => setRecipients(e.target.value)} fullWidth />
          <Button variant="contained" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>Schedule</Button>
        </Stack>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>Your schedules</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell><TableCell>Report</TableCell><TableCell>Repeat</TableCell>
              <TableCell>Next run</TableCell><TableCell>Recipients</TableCell><TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(schedules.data?.items ?? []).map((s) => (
              <TableRow key={s.id}>
                <TableCell>{s.name} {!s.active && <Chip size="small" label="paused" />}</TableCell>
                <TableCell>{s.report} · {s.format.toUpperCase()} · {s.window_days}d</TableCell>
                <TableCell>{s.cadence}</TableCell>
                <TableCell>{s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}</TableCell>
                <TableCell>{s.recipients.length}</TableCell>
                <TableCell align="right">
                  <Button size="small" onClick={() => runNow.mutate(s.id)}>Run now</Button>
                  <Button size="small" onClick={() => toggle.mutate(s)}>{s.active ? "Pause" : "Resume"}</Button>
                  <Button size="small" color="error" onClick={() => { if (window.confirm("Delete this schedule?")) remove.mutate(s.id); }}>Delete</Button>
                </TableCell>
              </TableRow>
            ))}
            {schedules.data && schedules.data.items.length === 0 && (
              <TableRow><TableCell colSpan={6}><Typography color="text.secondary">No schedules yet.</Typography></TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>Generated files</Typography>
        <Stack spacing={1}>
          {(runs.data?.items ?? []).map((r) => (
            <Stack key={r.id} direction="row" spacing={1} sx={{ alignItems: "center" }}>
              <Typography sx={{ flex: 1 }}>{r.filename} · {r.rows} rows · {new Date(r.created_at).toLocaleString()}</Typography>
              <Button size="small" onClick={() => download(`/v1/analytics/runs/${r.id}/download`, r.filename).catch((e) => onError(errorText(e)))}>
                Download
              </Button>
            </Stack>
          ))}
          {runs.data && runs.data.items.length === 0 && <Typography color="text.secondary">Nothing generated yet.</Typography>}
        </Stack>
      </Paper>
      <FormControlLabel control={<Checkbox checked disabled />} label="Schedules run on the server; the owner and recipients are notified in-app and by email when a file is ready." />
    </Stack>
  );
}
