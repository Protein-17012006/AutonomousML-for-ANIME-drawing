"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { ArrowLeft, Check } from "lucide-react";
import { confirmResetPassword } from "aws-amplify/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { configureAmplify } from "@/lib/amplify";
import { clearAuthFlow, readAuthFlow } from "@/lib/authFlow";

const CODE_LENGTH = 6;

export function ResetPasswordForm() {
  const [done, setDone] = useState(false);
  const flow = useSyncExternalStore(
    () => () => undefined,
    readAuthFlow,
    () => null,
  );
  const pendingEmail = flow?.intent === "reset-password" ? flow.email : "";
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    configureAmplify();
    setError(null);
    const form = new FormData(e.currentTarget);
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm-password") ?? "");
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (!pendingEmail) {
      setError("Request a new password reset code first.");
      return;
    }
    if (code.length !== CODE_LENGTH) {
      setError(`Enter the ${CODE_LENGTH}-digit confirmation code.`);
      return;
    }
    setSubmitting(true);
    try {
      await confirmResetPassword({
        username: pendingEmail,
        confirmationCode: code,
        newPassword: password,
      });
      clearAuthFlow();
      setDone(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not reset password.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="flex flex-col gap-5">
        <Alert>
          <Check className="mt-0.5 size-4 shrink-0 text-pass" />
          <AlertDescription>
            Your password has been updated. You can sign in now.
          </AlertDescription>
        </Alert>
        <Button asChild className="h-10 w-full">
          <Link href="/login">Continue to sign in</Link>
        </Button>
      </div>
    );
  }

  if (!pendingEmail) {
    return (
      <div className="flex flex-col gap-5">
        <Alert variant="destructive">
          <AlertDescription>
            No password-reset request was found. Request a new reset code to
            continue.
          </AlertDescription>
        </Alert>

        <Button asChild className="h-10 w-full">
          <Link href="/forgot-password">Request a new code</Link>
        </Button>

        <Button asChild variant="ghost" className="h-9 w-full">
          <Link href="/login">
            <ArrowLeft />
            Back to sign in
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={handleSubmit}>
        <FieldGroup className="gap-4">
          <Field data-invalid={!!error}>
            <FieldLabel htmlFor="code">Reset code</FieldLabel>
            <Input
              id="code"
              name="code"
              required
              inputMode="numeric"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="6-digit code"
              className="h-10"
              aria-invalid={!!error}
              aria-describedby={error ? "reset-password-error" : undefined}
            />
          </Field>

          <Field data-invalid={!!error}>
            <FieldLabel htmlFor="password">New password</FieldLabel>
            <Input
              id="password"
              name="password"
              type="password"
              required
              autoComplete="new-password"
              placeholder="At least 8 characters"
              className="h-10"
              aria-invalid={!!error}
              aria-describedby={error ? "reset-password-error" : undefined}
            />
          </Field>

          <Field data-invalid={!!error}>
            <FieldLabel htmlFor="confirm-password">
              Confirm new password
            </FieldLabel>
            <Input
              id="confirm-password"
              name="confirm-password"
              type="password"
              required
              autoComplete="new-password"
              placeholder="Re-enter your new password"
              className="h-10"
              aria-invalid={!!error}
              aria-describedby={error ? "reset-password-error" : undefined}
            />
          </Field>

          <Button type="submit" disabled={submitting} className="h-10 w-full">
            {submitting ? "Resetting..." : "Reset password"}
          </Button>
          {error && (
            <Alert id="reset-password-error" variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </FieldGroup>
      </form>

      <Button asChild variant="ghost" className="h-9 w-full">
        <Link href="/login">
          <ArrowLeft />
          Back to sign in
        </Link>
      </Button>
    </div>
  );
}
