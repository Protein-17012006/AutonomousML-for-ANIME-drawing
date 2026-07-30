"use client";

import {
  clearTemporaryAmplifySession,
  cognitoLogoutUrl,
  getCurrentIdToken,
} from "@/lib/amplify";

export const AUTH_REQUEST_TIMEOUT_MS = 8_000;
export type AuthRequestFailureKind = "unauthenticated" | "unavailable";

export class AuthRequestError extends Error {
  constructor(
    readonly kind: AuthRequestFailureKind,
    message: string,
  ) {
    super(message);
    this.name = "AuthRequestError";
  }
}

export function isAuthRequestError(
  error: unknown,
  kind: AuthRequestFailureKind,
): error is AuthRequestError {
  return error instanceof AuthRequestError && error.kind === kind;
}

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

async function authFetch(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs = AUTH_REQUEST_TIMEOUT_MS,
) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new AuthRequestError(
        "unavailable",
        "The co-pilot service did not respond in time.",
      );
    }
    throw new AuthRequestError(
      "unavailable",
      "The co-pilot service is temporarily unavailable.",
    );
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function establishCookieSession(timeoutMs?: number) {
  let idToken: string;
  try {
    idToken = await getCurrentIdToken();
  } catch {
    throw new AuthRequestError("unauthenticated", "Cognito sign-in is incomplete.");
  }
  const response = await authFetch(
    "/auth/session",
    {
      method: "POST",
      credentials: "same-origin",
      headers: { Authorization: `Bearer ${idToken}` },
    },
    timeoutMs,
  );
  if (!response.ok) {
    const detail = await responseDetail(response);
    throw new AuthRequestError(
      response.status === 401 ? "unauthenticated" : "unavailable",
      detail || `Session setup failed (${response.status}).`,
    );
  }
  await clearTemporaryAmplifySession();
}

export async function getCookieSession(
  timeoutMs?: number,
): Promise<CookieSession> {
  const response = await authFetch(
    "/auth/me",
    { credentials: "same-origin", cache: "no-store" },
    timeoutMs,
  );
  if (!response.ok) {
    throw new AuthRequestError(
      response.status === 401 ? "unauthenticated" : "unavailable",
      `Session check failed (${response.status}).`,
    );
  }
  const value: unknown = await response.json();
  if (!isCookieSession(value)) {
    throw new AuthRequestError("unavailable", "Invalid session response.");
  }
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
