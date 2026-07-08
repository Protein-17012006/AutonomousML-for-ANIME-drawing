"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { SocialAuthButtons } from "./SocialAuthButtons";

// Sign-up form. TEMPLATE ONLY — submit is a client-side stub (preventDefault); no auth yet.
// Stage 3 wires this to Firebase Auth. Plain <label> is used (no shadcn Label component installed).
export function SignupForm() {
  return (
    <div className="flex flex-col gap-5">
      <form
        onSubmit={(e) => e.preventDefault()}
        className="flex flex-col gap-4"
      >
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
            autoComplete="email"
            placeholder="you@studio.com"
            className="h-10"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label
            htmlFor="password"
            className="font-body text-sm font-medium text-foreground"
          >
            Password
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
            Confirm password
          </label>
          <Input
            id="confirm-password"
            name="confirm-password"
            type="password"
            autoComplete="new-password"
            placeholder="Re-enter your password"
            className="h-10"
          />
        </div>

        <Button
          type="submit"
          className="h-10 w-full border-0 bg-linear-to-r from-purple-500 to-pink-500 text-white hover:opacity-90"
        >
          Create account
        </Button>
      </form>

      <div className="flex items-center gap-3">
        <Separator className="flex-1" />
        <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">
          or continue with
        </span>
        <Separator className="flex-1" />
      </div>

      <SocialAuthButtons />

      <p className="text-center font-body text-sm text-muted-foreground">
        Already have an account?{" "}
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
