"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signUp } from "aws-amplify/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { SocialAuthButtons } from "./SocialAuthButtons";
import { configureAmplify } from "@/lib/amplify";

export function SignupForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    configureAmplify();
    setError(null);

    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const name = email.split("@", 1)[0]?.trim() || email;
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm-password") ?? "");
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      await signUp({
        username: email,
        password,
        options: {
          userAttributes: { email, name },
          autoSignIn: true,
        },
      });
      sessionStorage.setItem("copilot:pendingEmail", email);
      router.push("/verify-email");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign up failed.");
    } finally {
      setSubmitting(false);
    }
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
            placeholder="you@studio.com"
            className="h-10"
            aria-invalid={!!error}
            aria-describedby={error ? "signup-error" : undefined}
          />
        </Field>

        <Field data-invalid={!!error}>
          <FieldLabel htmlFor="password">Password</FieldLabel>
          <Input
            id="password"
            name="password"
            type="password"
            required
            autoComplete="new-password"
            placeholder="At least 8 characters"
            className="h-10"
            aria-invalid={!!error}
            aria-describedby={error ? "signup-error" : undefined}
          />
        </Field>

        <Field data-invalid={!!error}>
          <FieldLabel htmlFor="confirm-password">Confirm password</FieldLabel>
          <Input
            id="confirm-password"
            name="confirm-password"
            type="password"
            required
            autoComplete="new-password"
            placeholder="Re-enter your password"
            className="h-10"
            aria-invalid={!!error}
            aria-describedby={error ? "signup-error" : undefined}
          />
        </Field>

        <Button
          type="submit"
          disabled={submitting}
          className="h-10 w-full"
        >
          {submitting ? "Creating..." : "Create account"}
        </Button>
        {error && (
          <Alert id="signup-error" variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        </FieldGroup>
      </form>

      <div className="flex items-center gap-3">
        <Separator className="flex-1" />
        <span className="font-mono text-xs whitespace-nowrap text-ash">
          or continue with
        </span>
        <Separator className="flex-1" />
      </div>

      <SocialAuthButtons />

      <p className="text-center font-body text-sm text-ash">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-washi hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
