"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// New-password form (landed on from a reset link). TEMPLATE ONLY — submit is a client-side stub
// (preventDefault); nothing is saved. Stage 3 wires this to Firebase Auth (confirmPasswordReset).
// Plain <label> is used (no shadcn Label component installed). Shares AuthShell with the other auth pages.
export function ResetPasswordForm() {
  const [done, setDone] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setDone(true);
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
          <label
            htmlFor="password"
            className="font-body text-sm font-medium text-foreground"
          >
            New password
          </label>
          <Input
            id="password"
            name="password"
            type="password"
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
            autoComplete="new-password"
            placeholder="Re-enter your new password"
            className="h-10"
          />
        </div>

        <Button
          type="submit"
          className="h-10 w-full border-0 bg-linear-to-r from-purple-500 to-pink-500 text-white hover:opacity-90"
        >
          Reset password
        </Button>
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
