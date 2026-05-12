"use client";

import { clearSession, getAccessToken, setSession, type Role } from "./auth";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type Options = {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Skip auth header (login endpoint). */
  noAuth?: boolean;
};

async function refreshAccess(): Promise<string | null> {
  // Refresh cookie is HttpOnly + SameSite=Lax; the browser sends it automatically.
  const r = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!r.ok) return null;
  const body = await r.json();
  setSession(body.access_token, body.role);
  return body.access_token as string;
}

function buildUrl(path: string, query?: Options["query"]): string {
  const url = new URL(`${API_URL}${path}`);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const { method = "GET", body, query, noAuth = false } = opts;
  const url = buildUrl(path, query);
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const token = noAuth ? null : getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const init: RequestInit = {
    method,
    headers,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };

  let resp = await fetch(url, init);
  if (resp.status === 401 && !noAuth) {
    const refreshed = await refreshAccess();
    if (refreshed) {
      headers.Authorization = `Bearer ${refreshed}`;
      resp = await fetch(url, { ...init, headers });
    } else {
      clearSession();
    }
  }

  if (resp.status === 204) return undefined as T;

  const text = await resp.text();
  const parsed = text ? safeJson(text) : null;
  if (!resp.ok) {
    const code = parsed?.detail?.code ?? parsed?.code ?? "error";
    const message =
      parsed?.detail?.message ??
      parsed?.detail ??
      parsed?.message ??
      `request failed: ${resp.status}`;
    throw new ApiError(resp.status, String(code), String(message));
  }
  return parsed as T;
}

function safeJson(s: string): any {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

export async function login(email: string, password: string): Promise<Role> {
  const body = await api<{ access_token: string; role: Role }>(
    "/auth/login",
    { method: "POST", body: { email, password }, noAuth: true },
  );
  setSession(body.access_token, body.role);
  return body.role;
}

export async function logout(): Promise<void> {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch {
    /* even if the server errs, drop local state */
  }
  clearSession();
}

export type Page<T> = { items: T[]; total: number };
