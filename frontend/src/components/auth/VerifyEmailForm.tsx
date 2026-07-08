"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check } from "lucide-react";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { Button } from "@/components/ui/button";
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSeparator,
  InputOTPSlot,
} from "@/components/ui/input-otp";

// Email confirmation-code form. TEMPLATE ONLY — submit is a client-side stub (preventDefault); the
// code is not checked against anything. Stage 3 wires this to the real verification call. Uses the
// shadcn `input-otp` component (6 digits, split 3-3) for accessible type/paste/keyboard handling.
// Shares AuthShell with the other auth pages.
const CODE_LENGTH = 6;

export function VerifyEmailForm() {
  const [value, setValue] = useState("");
  const [verified, setVerified] = useState(false);

  const complete = value.length === CODE_LENGTH;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (complete) setVerified(true);
  }

  if (verified) {
    return (
      <div className="flex flex-col gap-5">
        <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 font-body text-sm text-foreground">
          <Check className="mt-0.5 size-4 shrink-0 text-emerald-500" />
          <span>Your email is verified. You can sign in now.</span>
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
        <div className="flex justify-center">
          <InputOTP
            maxLength={CODE_LENGTH}
            value={value}
            onChange={setValue}
            pattern={REGEXP_ONLY_DIGITS}
            autoFocus
          >
            <InputOTPGroup>
              <InputOTPSlot index={0} className="size-12 text-lg" />
              <InputOTPSlot index={1} className="size-12 text-lg" />
              <InputOTPSlot index={2} className="size-12 text-lg" />
            </InputOTPGroup>
            <InputOTPSeparator />
            <InputOTPGroup>
              <InputOTPSlot index={3} className="size-12 text-lg" />
              <InputOTPSlot index={4} className="size-12 text-lg" />
              <InputOTPSlot index={5} className="size-12 text-lg" />
            </InputOTPGroup>
          </InputOTP>
        </div>

        <Button
          type="submit"
          disabled={!complete}
          className="h-10 w-full border-0 bg-linear-to-r from-purple-500 to-pink-500 text-white hover:opacity-90"
        >
          Verify email
        </Button>
      </form>

      <p className="text-center font-body text-sm text-muted-foreground">
        Didn&apos;t get a code?{" "}
        <button
          type="button"
          className="font-medium text-foreground hover:underline"
        >
          Resend
        </button>
      </p>

      <Button asChild variant="ghost" className="h-9 w-full">
        <Link href="/login">
          <ArrowLeft />
          Back to sign in
        </Link>
      </Button>
    </div>
  );
}
