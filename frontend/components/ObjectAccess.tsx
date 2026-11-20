"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  CardContent,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { apiFetch, putJson } from "@/lib/api";
type Grant = { grantee_type: string; grantee_id: string; permission: string };
type Policy = {
  visibility: string;
  department_id: number | null;
  grants: Grant[];
};
export function ObjectAccess({ id }: { id: string }) {
  const client = useQueryClient();
  const result = useQuery({
    queryKey: ["object-access", id],
    queryFn: () => apiFetch<Policy>(`/v1/content/${id}/access`),
  });
  const [draft, setDraft] = useState<Policy | null>(null);
  const [grant, setGrant] = useState<Grant>({
    grantee_type: "user",
    grantee_id: "",
    permission: "read",
  });
  const policy = draft || result.data;
  const save = useMutation({
    mutationFn: () => putJson(`/v1/content/${id}/access`, policy),
    onSuccess: async () => {
      await client.invalidateQueries();
      setDraft(null);
    },
  });
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h6" component="h2">
            Object access
          </Typography>
          <Typography>
            Grants allow access within each recipient’s role permissions.
            Restricted objects are visible only to their owner, administrators,
            and grant recipients.
          </Typography>
          {(result.error || save.error) && (
            <Alert severity="error">
              {(result.error || save.error)?.message}
            </Alert>
          )}
          {save.isSuccess && (
            <Alert severity="success">Access policy saved.</Alert>
          )}
          {policy && (
            <>
              <TextField
                select
                label="Visibility"
                value={policy.visibility}
                onChange={(e) =>
                  setDraft({ ...policy, visibility: e.target.value })
                }
              >
                {["repository", "department", "restricted"].map((v) => (
                  <MenuItem key={v} value={v}>
                    {v}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                type="number"
                label="Department ID"
                value={policy.department_id ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...policy,
                    department_id: e.target.value
                      ? Number(e.target.value)
                      : null,
                  })
                }
              />
              {policy.grants.map((g, i) => (
                <Stack key={i} direction="row" spacing={2}>
                  <Typography>
                    {g.grantee_type} {g.grantee_id}: {g.permission}
                  </Typography>
                  <Button
                    onClick={() =>
                      setDraft({
                        ...policy,
                        grants: policy.grants.filter((_, index) => index !== i),
                      })
                    }
                  >
                    Remove
                  </Button>
                </Stack>
              ))}
              <TextField
                select
                label="Recipient type"
                value={grant.grantee_type}
                onChange={(e) =>
                  setGrant({ ...grant, grantee_type: e.target.value })
                }
              >
                {["user", "group", "department"].map((v) => (
                  <MenuItem key={v} value={v}>
                    {v}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="User subject or group/department ID"
                value={grant.grantee_id}
                onChange={(e) =>
                  setGrant({ ...grant, grantee_id: e.target.value })
                }
              />
              <TextField
                select
                label="Access"
                value={grant.permission}
                onChange={(e) =>
                  setGrant({ ...grant, permission: e.target.value })
                }
              >
                {["read", "edit", "review", "publish", "manage"].map((v) => (
                  <MenuItem key={v} value={v}>
                    {v}
                  </MenuItem>
                ))}
              </TextField>
              <Button
                disabled={!grant.grantee_id}
                onClick={() => {
                  setDraft({ ...policy, grants: [...policy.grants, grant] });
                  setGrant({ ...grant, grantee_id: "" });
                }}
              >
                Add grant
              </Button>
              <Button
                disabled={save.isPending}
                variant="contained"
                onClick={() => save.mutate()}
              >
                Save access policy
              </Button>
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
