"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Check } from "lucide-react";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { autoSignIn, confirmSignUp, resendSignUpCode } from "aws-amplify/auth";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSeparator,
  InputOTPSlot,
} from "@/components/ui/input-otp";
import { configureAmplify } from "@/lib/amplify";

const CODE_LENGTH = 6;

export function VerifyEmailForm() {
  const router = useRouter();
  const [value, setValue] = useState("");
  const email = useSyncExternalStore(
    () => () => undefined,
    () => sessionStorage.getItem("copilot:pendingEmail") ?? "",
    () => "",
  );
  const [verified, setVerified] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);

  const complete = value.length === CODE_LENGTH && !!email;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!complete) return;
    configureAmplify();
    setError(null);
    setSubmitting(true);
    try {
      await confirmSignUp({ username: email, confirmationCode: value });
      try {
        await autoSignIn();
        router.replace("/copilot");
      } catch {
        setVerified(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function resend() {
    if (!email || resending) return;
    configureAmplify();
    setError(null);
    setResending(true);
    try {
      await resendSignUpCode({ username: email });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resend the code.");
    } finally {
      setResending(false);
    }
  }

  if (verified) {
    return (
      <div className="flex flex-col gap-5">
        <Alert>
          <Check className="mt-0.5 size-4 shrink-0 text-pass" />
          <AlertDescription>Your email is verified. You can sign in now.</AlertDescription>
        </Alert>
        <Button
          asChild
          className="h-10 w-full"
        >
          <Link href="/login">Continue to sign in</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {!email && (
        <p className="text-center text-sm text-ash">
          Start from signup or sign in again so we know which email to verify.
        </p>
      )}
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex justify-center">
          <InputOTP
            id="verification-code"
            aria-label="Verification code"
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
          disabled={!complete || submitting}
          className="h-10 w-full"
        >
          {submitting ? "Verifying..." : "Verify email"}
        </Button>
        {error && (
          <Alert id="verify-email-error" variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </form>

      <p className="text-center font-body text-sm text-ash">
        Didn&apos;t get a code?{" "}
        <button
          type="button"
          onClick={resend}
          disabled={!email || resending}
          className="font-medium text-washi hover:underline"
        >
          {resending ? "Sending..." : "Resend"}
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
