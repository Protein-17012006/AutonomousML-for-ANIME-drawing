"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signIn } from "aws-amplify/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { SocialAuthButtons } from "./SocialAuthButtons";
import { configureAmplify, getCurrentIdToken } from "@/lib/amplify";
import { establishCookieSession } from "@/lib/authenticatedApi";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    configureAmplify();
    setError(null);
    setSubmitting(true);

    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");

    try {
      // Verification with autoSignIn can leave a valid Amplify session before
      // the application cookie is established. Recover it instead of asking
      // Cognito to sign in the same user a second time.
      let alreadySignedIn = false;
      try {
        await getCurrentIdToken();
        alreadySignedIn = true;
      } catch {
        // No current Cognito session: continue with the submitted credentials.
      }
      if (alreadySignedIn) {
        await establishCookieSession();
        router.replace("/copilot");
        return;
      }

      const result = await signIn({ username: email, password });
      sessionStorage.setItem("copilot:pendingEmail", email);
      if (result.nextStep.signInStep === "CONFIRM_SIGN_UP") {
        router.push("/verify-email");
      } else if (result.nextStep.signInStep === "RESET_PASSWORD") {
        router.push("/forgot-password");
      } else if (result.isSignedIn) {
        await establishCookieSession();
        router.replace("/copilot");
      } else {
        setError(
          `Additional sign-in step required: ${result.nextStep.signInStep}`,
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
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
              aria-describedby={error ? "login-error" : undefined}
            />
          </Field>

          <Field data-invalid={!!error}>
            <div className="flex items-center justify-between gap-2">
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Link
                href="/forgot-password"
                className="font-body text-xs text-ash transition-colors hover:text-washi"
              >
                Forgot password?
              </Link>
            </div>
            <Input
              id="password"
              name="password"
              type="password"
              required
              autoComplete="current-password"
              placeholder="Password"
              className="h-10"
              aria-invalid={!!error}
              aria-describedby={error ? "login-error" : undefined}
            />
          </Field>

          <Button type="submit" disabled={submitting} className="h-10 w-full">
            {submitting ? "Signing in..." : "Sign in"}
          </Button>
          {error && (
            <Alert id="login-error" variant="destructive">
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
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="font-medium text-washi hover:underline">
          Sign up
        </Link>
      </p>
    </div>
  );
}
