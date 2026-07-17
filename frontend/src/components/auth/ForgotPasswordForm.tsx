"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Check } from "lucide-react";
import { resetPassword } from "aws-amplify/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { configureAmplify } from "@/lib/amplify";

export function ForgotPasswordForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    configureAmplify();
    setError(null);
    setSubmitting(true);
    try {
      await resetPassword({ username: email.trim() });
      sessionStorage.setItem("copilot:pendingEmail", email.trim());
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send reset code.");
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <div className="flex flex-col gap-5">
        <Alert>
          <Check className="mt-0.5 size-4 shrink-0 text-pass" />
          <AlertDescription>
            If an account exists for <span className="font-medium">{email}</span>, a reset code is on
            its way.
          </AlertDescription>
        </Alert>
        <Button
          type="button"
          onClick={() => router.push("/reset-password")}
          className="h-10 w-full"
        >
          Enter reset code
        </Button>
        <Button asChild variant="outline" className="h-10 w-full">
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
          <FieldLabel htmlFor="email">Email</FieldLabel>
          <Input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@studio.com"
            className="h-10"
            aria-invalid={!!error}
            aria-describedby={error ? "forgot-password-error" : undefined}
          />
        </Field>

        <Button
          type="submit"
          disabled={submitting}
          className="h-10 w-full"
        >
          {submitting ? "Sending..." : "Send reset code"}
        </Button>
        {error && (
          <Alert id="forgot-password-error" variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        </FieldGroup>
      </form>

      <p className="text-center font-body text-sm text-ash">
        Remember your password?{" "}
        <Link href="/login" className="font-medium text-washi hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
