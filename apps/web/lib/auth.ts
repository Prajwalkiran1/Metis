"use client";

const ACCESS_KEY = "metis.access";
const ROLE_KEY = "metis.role";

export type Role = "admin" | "teacher" | "student";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getRole(): Role | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ROLE_KEY) as Role | null;
}

export function setSession(access: string, role: Role): void {
  window.localStorage.setItem(ACCESS_KEY, access);
  window.localStorage.setItem(ROLE_KEY, role);
}

export function clearSession(): void {
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(ROLE_KEY);
}
