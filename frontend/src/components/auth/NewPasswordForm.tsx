"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { confirmSignIn } from "aws-amplify/auth";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { configureAmplify } from "@/lib/amplify";
import { establishCookieSession } from "@/lib/authenticatedApi";
import { clearAuthFlow, readAuthFlow } from "@/lib/authFlow";

export function NewPasswordForm() {
  const router = useRouter();
  const flow = useSyncExternalStore(
    () => () => undefined,
    readAuthFlow,
    () => null,
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    configureAmplify();
    setError(null);
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    const confirmation = String(form.get("confirm-password") ?? "");
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await confirmSignIn({ challengeResponse: password });
      if (!result.isSignedIn) {
        setError("Another sign-in step is required. Return to sign in and try again.");
        return;
      }
      await establishCookieSession();
      clearAuthFlow();
      router.replace("/copilot");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update password.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-center text-sm text-ash">
        Cognito requires a new password before {flow?.email ?? "this account"} can sign in.
      </p>
      <form onSubmit={handleSubmit}>
        <FieldGroup className="gap-4">
          <Field data-invalid={!!error}>
            <FieldLabel htmlFor="password">New password</FieldLabel>
            <Input id="password" name="password" type="password" required autoComplete="new-password" />
          </Field>
          <Field data-invalid={!!error}>
            <FieldLabel htmlFor="confirm-password">Confirm new password</FieldLabel>
            <Input id="confirm-password" name="confirm-password" type="password" required autoComplete="new-password" />
          </Field>
          <Button type="submit" disabled={submitting} className="h-10 w-full">
            {submitting ? "Updating..." : "Set new password"}
          </Button>
          {error && (
            <Alert id="new-password-error" variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </FieldGroup>
      </form>
      <Button asChild variant="ghost" className="h-9 w-full">
        <Link href="/login">Back to sign in</Link>
      </Button>
    </div>
  );
}
