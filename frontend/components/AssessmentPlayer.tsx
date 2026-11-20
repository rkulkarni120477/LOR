"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  FormControlLabel,
  Radio,
  RadioGroup,
  Stack,
  Typography,
} from "@mui/material";
import { apiFetch, postJson } from "@/lib/api";
import type { Preview } from "@/components/LibraryPreview";
import { can, loadSession } from "@/lib/auth";
export function AssessmentPlayer({ item }: { item: Preview }) {
  const client = useQueryClient();
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const submit = useMutation({
    mutationFn: () =>
      postJson<{ score: number; passed: boolean }>(
        `/v1/library/${item.id}/attempts`,
        {
          revision: item.revision,
          answers: item.questions?.map((_, i) => answers[i] ?? -1),
        },
      ),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["attempts", item.id] }),
  });
  const history = useQuery({
    queryKey: ["attempts", item.id],
    queryFn: () =>
      apiFetch<{ items: { id: string; score: number; passed: boolean }[] }>(
        `/v1/library/${item.id}/attempts`,
      ),
  });
  return (
    <Stack spacing={2}>
      <Typography variant="h6">Take this {item.kind}</Typography>
      {item.questions?.map((q, i) => (
        <div key={i}>
          <Typography>
            {i + 1}. {q.prompt}
          </Typography>
          <RadioGroup
            value={answers[i] ?? ""}
            onChange={(e) =>
              setAnswers({ ...answers, [i]: Number(e.target.value) })
            }
            aria-label={`Answer question ${i + 1}`}
          >
            {q.options.map((option, n) => (
              <FormControlLabel
                key={n}
                value={n}
                control={<Radio />}
                label={option}
              />
            ))}
          </RadioGroup>
        </div>
      ))}
      <Button
        variant="contained"
        disabled={
          submit.isPending ||
          !item.questions?.length ||
          Object.keys(answers).length !== item.questions.length ||
          !can(loadSession(), "activity.write")
        }
        onClick={() => submit.mutate()}
      >
        Submit answers
      </Button>
      {submit.error && <Alert severity="error">{submit.error.message}</Alert>}
      {submit.data && (
        <Alert severity={submit.data.passed ? "success" : "info"}>
          Score: {submit.data.score}% ·{" "}
          {submit.data.passed ? "Passed" : "Not passed"}
        </Alert>
      )}
      {history.data?.items.map((h) => (
        <Typography key={h.id} variant="body2">
          Previous attempt: {h.score}% · {h.passed ? "Passed" : "Not passed"}
        </Typography>
      ))}
    </Stack>
  );
}
