// Calls go through the Next.js route handler at /api/* which forwards to FastAPI.
import { loadSession } from "./auth";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function authHeader(): Record<string, string> {
  const session = loadSession();
  return session?.token ? { Authorization: `Bearer ${session.token}` } : {};
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  for (const [k, v] of Object.entries(authHeader()))
    if (!headers.has(k)) headers.set(k, v);
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as {
        message?: string;
        detail?: unknown;
      };
      if (body.message) message = body.message;
      else if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((item: {loc?: string[]; msg?: string}) => `${item.loc?.slice(1).join(".") || "Input"}: ${item.msg || "Invalid value"}`).join("; ");
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, message);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}

/** Fetches a binary or text resource through the proxy, with the bearer token attached. */
export async function apiBlob(path: string): Promise<Blob> {
  const headers = new Headers(authHeader());
  const response = await fetch(`/api${path}`, { headers, cache: "no-store" });
  if (!response.ok)
    throw new ApiError(response.status, `Request failed (${response.status})`);
  return response.blob();
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export function putJson<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "PUT", body: JSON.stringify(body) });
}
