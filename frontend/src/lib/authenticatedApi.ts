"use client";

import {
  clearTemporaryAmplifySession,
  cognitoLogoutUrl,
  getCurrentIdToken,
} from "@/lib/amplify";

export interface CookieSession {
  user_sub: string;
  username: string | null;
  name?: string | null;
  expires_at: number;
}

function isCookieSession(value: unknown): value is CookieSession {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as CookieSession).user_sub === "string" &&
    typeof (value as CookieSession).expires_at === "number" &&
    (!Object.hasOwn(value, "name") ||
      (value as CookieSession).name === null ||
      typeof (value as CookieSession).name === "string")
  );
}

async function responseDetail(response: Response) {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}

export async function establishCookieSession() {
  const idToken = await getCurrentIdToken();
  const response = await fetch("/auth/session", {
    method: "POST",
    credentials: "same-origin",
    headers: { Authorization: `Bearer ${idToken}` },
  });
  if (!response.ok) {
    const detail = await responseDetail(response);
    throw new Error(detail || `Session setup failed (${response.status}).`);
  }
  await clearTemporaryAmplifySession();
}

export async function getCookieSession(): Promise<CookieSession> {
  const response = await fetch("/auth/me", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Session check failed (${response.status}).`);
  const value: unknown = await response.json();
  if (!isCookieSession(value)) throw new Error("Invalid session response.");
  return value;
}

export async function logoutCookieSession() {
  try {
    await fetch("/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
  } finally {
    await clearTemporaryAmplifySession();
    window.location.assign(cognitoLogoutUrl());
  }
}

function redirectExpiredSession() {
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.replace("/login");
  }
}

export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
) {
  const response = await fetch(input, {
    ...init,
    credentials: "same-origin",
  });
  if (response.status === 401) redirectExpiredSession();
  return response;
}
