"use client";

import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Popover,
  Stack,
  Typography,
} from "@mui/material";
import { apiFetch, postJson } from "@/lib/api";
import { Icon } from "@/components/Icon";

type Notification = {
  id: number;
  kind: string;
  title: string;
  body: string;
  lo_id: string | null;
  created_at: string;
  read: boolean;
};

/** In-app notifications for the signed-in user. Polls lightly so new reviews show up. */
export function NotificationsMenu() {
  const queryClient = useQueryClient();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const feed = useQuery({
    queryKey: ["notifications"],
    queryFn: () => apiFetch<{ items: Notification[]; unread: number }>("/v1/notifications?limit=30"),
    refetchInterval: 60_000,
    retry: false,
  });
  const markRead = useMutation({
    mutationFn: (id: number) => postJson(`/v1/notifications/${id}/read`, {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const markAll = useMutation({
    mutationFn: () => postJson("/v1/notifications/read-all", {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  if (feed.error) return null; // Signed out, or the feed is unavailable. The bell stays hidden.

  return (
    <>
      <IconButton aria-label="Notifications" onClick={(e) => setAnchor(e.currentTarget)} sx={{ color: "inherit" }}>
        <Badge color="error" badgeContent={feed.data?.unread ?? 0} max={99}>
          <Icon name="bell" size={22} />
        </Badge>
      </IconButton>
      <Popover
        open={!!anchor}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <Stack sx={{ width: 360, maxHeight: 460 }}>
          <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", p: 2 }}>
            <Typography sx={{ fontWeight: 600 }}>Notifications</Typography>
            <Button size="small" disabled={!feed.data?.unread} onClick={() => markAll.mutate()}>
              Mark all read
            </Button>
          </Stack>
          <List dense sx={{ overflowY: "auto" }}>
            {(feed.data?.items ?? []).map((n) => (
              <ListItemButton
                key={n.id}
                component={n.lo_id ? RouterLink : "div"}
                to={n.lo_id ? `/objects?id=${n.lo_id}` : undefined}
                onClick={() => {
                  if (!n.read) markRead.mutate(n.id);
                  setAnchor(null);
                }}
                sx={{ opacity: n.read ? 0.6 : 1 }}
              >
                <ListItemText
                  primary={n.title}
                  secondary={`${n.body ? n.body.slice(0, 140) + " · " : ""}${new Date(n.created_at).toLocaleString()}`}
                />
              </ListItemButton>
            ))}
            {(feed.data?.items ?? []).length === 0 && (
              <Typography color="text.secondary" sx={{ p: 2 }}>
                You are all caught up.
              </Typography>
            )}
          </List>
        </Stack>
      </Popover>
    </>
  );
}
