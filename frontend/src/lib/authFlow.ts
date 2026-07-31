export type AuthFlowIntent =
  | "verify-email"
  | "reset-password"
  | "new-password";

export interface AuthFlow {
  email: string;
  intent: AuthFlowIntent;
}

const AUTH_FLOW_KEY = "copilot:authFlow";

export function readAuthFlow(): AuthFlow | null {
  if (typeof window === "undefined") return null;
  try {
    const value: unknown = JSON.parse(
      window.sessionStorage.getItem(AUTH_FLOW_KEY) ?? "null",
    );
    if (
      typeof value === "object" &&
      value !== null &&
      typeof (value as AuthFlow).email === "string" &&
      ["verify-email", "reset-password", "new-password"].includes(
        (value as AuthFlow).intent,
      )
    ) {
      return value as AuthFlow;
    }
  } catch {
    // Treat malformed tab-local state as absent; never trust it for access.
  }
  return null;
}

export function setAuthFlow(intent: AuthFlowIntent, email: string) {
  const normalizedEmail = email.trim();
  if (!normalizedEmail) throw new Error("An email is required for this auth flow.");
  window.sessionStorage.setItem(
    AUTH_FLOW_KEY,
    JSON.stringify({ email: normalizedEmail, intent } satisfies AuthFlow),
  );
}

export function clearAuthFlow() {
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(AUTH_FLOW_KEY);
  }
}
