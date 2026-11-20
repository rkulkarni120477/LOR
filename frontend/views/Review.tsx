"use client";

import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Chip,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { PackagePreview } from "@/components/PackagePreview";
import { ApiError, apiFetch, postJson } from "@/lib/api";
import { loadSession } from "@/lib/auth";

type QueueTask = {
  task_id: number;
  lo_id: string;
  title: string;
  stage: string;
  round: number;
  policy: string;
  pooled: boolean;
  due_at: string | null;
  overdue: boolean;
};
type CaseView = {
  id: string;
  round: number;
  status: string;
  policy: string;
  stage_position: number;
  submitted_by: string;
  stages: { position: number; name: string; permission: string; approvals_required: number }[];
  tasks: { id: number; stage: number; state: string; assignee: string | null; decided_by: string | null; comment: string | null }[];
  history: { from: string | null; to: string; by: string; comment: string | null; at: string }[];
};
type Item = { id: string; title: string; status: string; created_by: string };

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong";
}

export default function ReviewPage() {
  const [tab, setTab] = useState<"queue" | "mine">("queue");
  return (
    <Stack spacing={2}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        Workflow
      </Typography>
      <Tabs value={tab} onChange={(_, value) => setTab(value)}>
        <Tab value="queue" label="My review queue" />
        <Tab value="mine" label="My submissions" />
      </Tabs>
      {tab === "queue" ? <ReviewQueue /> : <MySubmissions />}
    </Stack>
  );
}

function ReviewQueue() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<QueueTask | null>(null);
  const [comment, setComment] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const queue = useQuery({
    queryKey: ["workflow-queue"],
    queryFn: () => apiFetch<{ items: QueueTask[] }>("/v1/workflow/queue"),
  });
  const caseView = useQuery({
    queryKey: ["workflow-case", selected?.lo_id],
    queryFn: () => apiFetch<CaseView>(`/v1/workflow/${selected!.lo_id}/case`),
    enabled: !!selected,
  });

  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject" | "request_changes") =>
      postJson<{ status: string }>(`/v1/workflow/${selected!.lo_id}/decision`, {
        decision,
        comment: comment.trim() || null,
      }),
    onSuccess: (result, decision) => {
      setMessage(`${decision.replace("_", " ")} recorded. Item is now ${result.status}.`);
      setSelected(null);
      setComment("");
      void queryClient.invalidateQueries({ queryKey: ["workflow-queue"] });
    },
    onError: (error) => setMessage(errorText(error)),
  });

  const session = loadSession();
  const needsComment = !comment.trim();

  return (
    <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: "flex-start" }}>
      <Stack spacing={1} sx={{ flex: 1, width: "100%" }}>
        {message && <Alert severity="info" onClose={() => setMessage(null)}>{message}</Alert>}
        {queue.error && <Alert severity="error">{errorText(queue.error)}</Alert>}
        {(queue.data?.items ?? []).length === 0 && !queue.isLoading && (
          <Typography color="text.secondary">Nothing is waiting for you.</Typography>
        )}
        {(queue.data?.items ?? []).map((task) => (
          <Paper
            key={task.task_id}
            onClick={() => setSelected(task)}
            role="button"
            aria-pressed={selected?.task_id === task.task_id}
            sx={{ p: 2, cursor: "pointer", outline: selected?.task_id === task.task_id ? "2px solid #1762c4" : "none" }}
          >
            <Typography sx={{ fontWeight: 600 }}>{task.title}</Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap", gap: 1 }}>
              <Chip size="small" label={`${task.stage} · round ${task.round}`} />
              <Chip size="small" variant="outlined" label={task.policy} />
              {task.pooled && <Chip size="small" variant="outlined" label="Open to your role" />}
              {task.overdue && <Chip size="small" color="error" label="Overdue" />}
            </Stack>
          </Paper>
        ))}
      </Stack>

      <Paper sx={{ p: 2, flex: 1, width: "100%" }}>
        {!selected && <Typography color="text.secondary">Select a review to decide on it.</Typography>}
        {selected && (
          <Stack spacing={2}>
            <Typography variant="h6">{selected.title}</Typography>
            {caseView.data && (
              <Stack spacing={0.5}>
                <Typography variant="body2">
                  Stage {caseView.data.stage_position} of {caseView.data.stages.length}:{" "}
                  {caseView.data.stages[caseView.data.stage_position - 1]?.name} ·{" "}
                  {caseView.data.stages[caseView.data.stage_position - 1]?.approvals_required} approval(s) needed
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Submitted by {caseView.data.submitted_by}
                </Typography>
                {caseView.data.history.slice(-3).map((h) => (
                  <Typography key={h.at} variant="body2" color="text.secondary">
                    {h.from ?? "start"} → {h.to} by {h.by}{h.comment ? `: “${h.comment}”` : ""}
                  </Typography>
                ))}
              </Stack>
            )}
            <PackagePreview key={selected.lo_id} loId={selected.lo_id} />
            <TextField
              label="Comment (required to reject or request changes)"
              multiline
              minRows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
              <Button variant="contained" disabled={decide.isPending} onClick={() => decide.mutate("approve")}>
                Approve
              </Button>
              <Button variant="outlined" disabled={needsComment || decide.isPending} onClick={() => decide.mutate("request_changes")}>
                Request changes
              </Button>
              <Button color="error" variant="outlined" disabled={needsComment || decide.isPending} onClick={() => decide.mutate("reject")}>
                Reject
              </Button>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              Signed in as {session?.email ?? session?.subject ?? "unknown"}. You cannot decide on your own submission.
            </Typography>
          </Stack>
        )}
      </Paper>
    </Stack>
  );
}

function MySubmissions() {
  const queryClient = useQueryClient();
  const session = loadSession();
  const [comment, setComment] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const items = useQuery({
    queryKey: ["my-submissions"],
    queryFn: () => apiFetch<{ items: Item[] }>("/v1/content?page_size=100"),
  });
  const mine = (items.data?.items ?? []).filter(
    (i) => i.created_by === session?.subject && ["submitted", "rejected", "under_review"].includes(i.status),
  );
  const act = useMutation({
    mutationFn: ({ id, path }: { id: string; path: "resubmit" | "withdraw" }) =>
      postJson<{ status: string }>(`/v1/workflow/${id}/${path}`, { comment: comment[id] || null }),
    onSuccess: (result) => {
      setMessage(`Item is now ${result.status}.`);
      void queryClient.invalidateQueries({ queryKey: ["my-submissions"] });
    },
    onError: (error) => setMessage(errorText(error)),
  });

  return (
    <Stack spacing={2}>
      {message && <Alert severity="info" onClose={() => setMessage(null)}>{message}</Alert>}
      {mine.length === 0 && <Typography color="text.secondary">No submissions are waiting on a decision or changes.</Typography>}
      {mine.map((item) => (
        <Paper key={item.id} sx={{ p: 2 }}>
          <Stack spacing={1}>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", gap: 1 }}>
              <Typography sx={{ fontWeight: 600 }}>{item.title}</Typography>
              <Chip size="small" label={item.status === "rejected" ? "Changes requested" : item.status} />
              <Button component={RouterLink} to={`/objects?id=${item.id}`} size="small">Open</Button>
            </Stack>
            <TextField
              size="small"
              label="Note for the reviewer"
              value={comment[item.id] ?? ""}
              onChange={(e) => setComment({ ...comment, [item.id]: e.target.value })}
            />
            <Stack direction="row" spacing={1}>
              {item.status === "rejected" && (
                <Button variant="contained" size="small" onClick={() => act.mutate({ id: item.id, path: "resubmit" })}>
                  Resubmit for review
                </Button>
              )}
              {item.status === "submitted" && (
                <Button size="small" onClick={() => act.mutate({ id: item.id, path: "withdraw" })}>
                  Withdraw
                </Button>
              )}
            </Stack>
          </Stack>
        </Paper>
      ))}
    </Stack>
  );
}
