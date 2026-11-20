"use client";

import { useEffect } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import { clearToken, loadSession, saveVerifiedSession } from "@/lib/auth";

export function SessionBootstrap() {
  useEffect(() => {
    let active = true;
    async function refresh() {
      const token = loadSession()?.token || "";
      try {
        const data =
          await apiFetch<Parameters<typeof saveVerifiedSession>[0]>(
            "/v1/auth/me",
          );
        if (active) saveVerifiedSession(data, token);
      } catch (error) {
        if (
          active &&
          error instanceof ApiError &&
          [401, 403].includes(error.status)
        )
          clearToken();
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  return null;
}
