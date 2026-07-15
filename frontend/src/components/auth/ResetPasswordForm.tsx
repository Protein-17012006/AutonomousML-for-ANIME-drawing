"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { ArrowLeft, Check } from "lucide-react";
import { confirmResetPassword } from "aws-amplify/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { configureAmplify } from "@/lib/amplify";

export function ResetPasswordForm() {
  const [done, setDone] = useState(false);
  const pendingEmail = useSyncExternalStore(
    () => () => undefined,
    () => sessionStorage.getItem("copilot:pendingEmail") ?? "",
    () => "",
  );
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    configureAmplify();
    setError(null);
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm-password") ?? "");
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await confirmResetPassword({
        username: email,
        confirmationCode: code,
        newPassword: password,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset password.");
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="flex flex-col gap-5">
        <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 font-body text-sm text-foreground">
          <Check className="mt-0.5 size-4 shrink-0 text-emerald-500" />
          <span>Your password has been updated. You can sign in now.</span>
        </div>
        <Button
          asChild
          className="h-10 w-full border-0 bg-linear-to-r from-purple-500 to-pink-500 text-white hover:opacity-90"
        >
          <Link href="/login">Continue to sign in</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <label htmlFor="email" className="font-body text-sm font-medium text-foreground">
            Email
          </label>
          <Input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            defaultValue={pendingEmail}
            placeholder="you@studio.com"
            className="h-10"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="code" className="font-body text-sm font-medium text-foreground">
            Reset code
          </label>
          <Input
            id="code"
            name="code"
            required
            inputMode="numeric"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="6-digit code"
            className="h-10"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="password" className="font-body text-sm font-medium text-foreground">
            New password
          </label>
          <Input
            id="password"
            name="password"
            type="password"
            required
            autoComplete="new-password"
            placeholder="At least 8 characters"
            className="h-10"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label
            htmlFor="confirm-password"
            className="font-body text-sm font-medium text-foreground"
          >
            Confirm new password
          </label>
          <Input
            id="confirm-password"
            name="confirm-password"
            type="password"
            required
            autoComplete="new-password"
            placeholder="Re-enter your new password"
            className="h-10"
          />
        </div>

        <Button
          type="submit"
          disabled={submitting}
          className="h-10 w-full border-0 bg-linear-to-r from-purple-500 to-pink-500 text-white hover:opacity-90"
        >
          {submitting ? "Resetting..." : "Reset password"}
        </Button>
        {error && <p className="text-sm text-destructive">{error}</p>}
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
