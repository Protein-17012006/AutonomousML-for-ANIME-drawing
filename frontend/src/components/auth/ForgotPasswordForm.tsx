"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Forgot-password form. TEMPLATE ONLY — submit is a client-side stub (preventDefault); no email is
// actually sent. Stage 3 wires this to Firebase Auth (sendPasswordResetEmail). Plain <label> is used
// (no shadcn Label component installed), matching LoginForm / SignupForm.
export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (email.trim()) setSent(true);
  }

  if (sent) {
    return (
      <div className="flex flex-col gap-5">
        <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 font-body text-sm text-foreground">
          <Check className="mt-0.5 size-4 shrink-0 text-emerald-500" />
          <span>
            If an account exists for{" "}
            <span className="font-medium">{email}</span>, a reset link is on its
            way. Check your inbox and spam folder.
          </span>
        </div>
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
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <label
            htmlFor="email"
            className="font-body text-sm font-medium text-foreground"
          >
            Email
          </label>
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
          />
        </div>

        <Button
          type="submit"
          className="h-10 w-full border-0 bg-linear-to-r from-purple-500 to-pink-500 text-white hover:opacity-90"
        >
          Send reset link
        </Button>
      </form>

      <p className="text-center font-body text-sm text-muted-foreground">
        Remember your password?{" "}
        <Link
          href="/login"
          className="font-medium text-foreground hover:underline"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
