"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Checkbox,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { apiFetch, postJson, putJson } from "@/lib/api";
import { can, loadSession } from "@/lib/auth";
type Department = { id: number; name: string };
type User = {
  subject: string;
  display_name: string;
  disabled: boolean;
  department_id: number | null;
  roles: string[];
};
type Group = {
  id: number;
  name: string;
  department_id: number | null;
  roles: string[];
  member_subjects: string[];
};
const newUser: User = {
  subject: "",
  display_name: "",
  disabled: false,
  department_id: null,
  roles: [],
};
const newGroup: Group = {
  id: 0,
  name: "",
  department_id: null,
  roles: [],
  member_subjects: [],
};
function Multi({
  label,
  values,
  options,
  change,
}: {
  label: string;
  values: string[];
  options: string[];
  change: (v: string[]) => void;
}) {
  return (
    <TextField
      select
      label={label}
      value={values}
      slotProps={{ select: { multiple: true } }}
      onChange={(e) =>
        change(
          typeof e.target.value === "string"
            ? e.target.value.split(",")
            : e.target.value,
        )
      }
    >
      {options.map((v) => (
        <MenuItem key={v} value={v}>
          {v}
        </MenuItem>
      ))}
    </TextField>
  );
}
export default function Administration() {
  const client = useQueryClient(),
    session = loadSession();
  const [department, setDepartment] = useState({ id: 0, name: "" });
  const [user, setUser] = useState<User>(newUser),
    [group, setGroup] = useState<Group>(newGroup);
  const departments = useQuery({
    queryKey: ["admin", "departments"],
    queryFn: () => apiFetch<{ items: Department[] }>("/v1/admin/departments"),
  });
  const users = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => apiFetch<{ items: User[] }>("/v1/admin/users"),
  });
  const groups = useQuery({
    queryKey: ["admin", "groups"],
    queryFn: () => apiFetch<{ items: Group[] }>("/v1/admin/groups"),
  });
  const roles = useQuery({
    queryKey: ["admin", "roles"],
    queryFn: () =>
      apiFetch<{ items: { name: string; permissions: string[] }[] }>(
        "/v1/admin/roles",
      ),
  });
  const mutation = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["admin"] });
    },
  });
  const error =
    mutation.error ||
    departments.error ||
    users.error ||
    groups.error ||
    roles.error;
  if (!can(session, "organization.manage"))
    return (
      <Alert severity="warning">
        Organization administration permission is required.
      </Alert>
    );
  const roleOptions = roles.data?.items.map((r) => r.name) || [];
  function departmentField(
    value: number | null,
    change: (id: number | null) => void,
  ) {
    return (
      <TextField
        select
        label="Department"
        value={value ?? ""}
        onChange={(e) =>
          change(e.target.value === "" ? null : Number(e.target.value))
        }
      >
        <MenuItem value="">None</MenuItem>
        {departments.data?.items.map((d) => (
          <MenuItem key={d.id} value={d.id}>
            {d.name}
          </MenuItem>
        ))}
      </TextField>
    );
  }
  return (
    <Stack spacing={3}>
      <Typography variant="h4" component="h1">
        Administration
      </Typography>
      {error && <Alert severity="error">{error.message}</Alert>}
      {mutation.isSuccess && (
        <Alert severity="success">
          Saved. Access changes apply to subsequent API requests.
        </Alert>
      )}
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6" component="h2">
              Departments
            </Typography>
            <Stack direction="row" sx={{ flexWrap: "wrap" }}>
              {departments.data?.items.map((d) => (
                <Button key={d.id} onClick={() => setDepartment(d)}>
                  {d.name}
                </Button>
              ))}
            </Stack>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                mutation.mutate(() =>
                  department.id
                    ? putJson(`/v1/admin/departments/${department.id}`, {
                        name: department.name,
                      })
                    : postJson("/v1/admin/departments", {
                        name: department.name,
                      }),
                );
              }}
            >
              <Stack spacing={2}>
                <TextField
                  required
                  label="Department name"
                  value={department.name}
                  onChange={(e) =>
                    setDepartment({ ...department, name: e.target.value })
                  }
                />
                <Button disabled={mutation.isPending} type="submit">
                  Save department
                </Button>
                <Button onClick={() => setDepartment({ id: 0, name: "" })}>
                  New department
                </Button>
              </Stack>
            </form>
          </Stack>
        </CardContent>
      </Card>
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6" component="h2">
              Users and role assignments
            </Typography>
            <Typography>
              Use the exact subject identifier issued by your identity provider.
              Local role assignments override provider roles; group roles are
              added separately.
            </Typography>
            <Stack direction="row" sx={{ flexWrap: "wrap" }}>
              {users.data?.items.map((u) => (
                <Button
                  key={u.subject}
                  onClick={() =>
                    setUser({
                      subject: u.subject,
                      display_name: u.display_name || "",
                      department_id: u.department_id,
                      disabled: u.disabled,
                      roles: u.roles,
                    })
                  }
                >
                  {u.display_name || u.subject}
                  {u.disabled ? " (disabled)" : ""}
                </Button>
              ))}
            </Stack>
            {can(session, "users.manage") ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  mutation.mutate(() => putJson("/v1/admin/users", user));
                }}
              >
                <Stack spacing={2}>
                  <TextField
                    required
                    label="Identity subject"
                    value={user.subject}
                    onChange={(e) =>
                      setUser({ ...user, subject: e.target.value })
                    }
                  />
                  <TextField
                    label="Display name"
                    value={user.display_name}
                    onChange={(e) =>
                      setUser({ ...user, display_name: e.target.value })
                    }
                  />
                  {departmentField(user.department_id, (id) =>
                    setUser({ ...user, department_id: id }),
                  )}
                  <Multi
                    label="Direct roles"
                    values={user.roles}
                    options={roleOptions}
                    change={(v) => setUser({ ...user, roles: v })}
                  />
                  <FormControlLabel
                    label="Disable account"
                    control={
                      <Checkbox
                        checked={user.disabled}
                        onChange={(e) =>
                          setUser({ ...user, disabled: e.target.checked })
                        }
                      />
                    }
                  />
                  <Button
                    variant="contained"
                    disabled={mutation.isPending}
                    type="submit"
                  >
                    Save user access
                  </Button>
                  <Button onClick={() => setUser(newUser)}>New user</Button>
                </Stack>
              </form>
            ) : (
              <Alert severity="info">
                A super administrator manages direct user access.
              </Alert>
            )}
          </Stack>
        </CardContent>
      </Card>
      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6" component="h2">
              Groups
            </Typography>
            <Stack direction="row" sx={{ flexWrap: "wrap" }}>
              {groups.data?.items.map((g) => (
                <Button key={g.id} onClick={() => setGroup(g)}>
                  {g.name}
                </Button>
              ))}
            </Stack>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const { id, ...body } = group;
                mutation.mutate(() => putJson(`/v1/admin/groups/${id}`, body));
              }}
            >
              <Stack spacing={2}>
                <TextField
                  required
                  label="Group name"
                  value={group.name}
                  onChange={(e) => setGroup({ ...group, name: e.target.value })}
                />
                {departmentField(group.department_id, (id) =>
                  setGroup({ ...group, department_id: id }),
                )}
                <Multi
                  label="Members (identity subjects)"
                  values={group.member_subjects}
                  options={users.data?.items.map((u) => u.subject) || []}
                  change={(v) => setGroup({ ...group, member_subjects: v })}
                />
                <Multi
                  label="Group roles"
                  values={group.roles}
                  options={roleOptions}
                  change={(v) => setGroup({ ...group, roles: v })}
                />
                <Button
                  variant="contained"
                  disabled={mutation.isPending}
                  type="submit"
                >
                  Save group
                </Button>
                <Button onClick={() => setGroup(newGroup)}>New group</Button>
              </Stack>
            </form>
          </Stack>
        </CardContent>
      </Card>
      <Card variant="outlined">
        <CardContent>
          <Typography variant="h6" component="h2">
            Nine-role permission model
          </Typography>
          {roles.data?.items.map((r) => (
            <Typography key={r.name} sx={{ my: 1 }}>
              <strong>{r.name}</strong>: {r.permissions.join(", ")}
            </Typography>
          ))}
        </CardContent>
      </Card>
    </Stack>
  );
}
