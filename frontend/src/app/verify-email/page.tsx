import type { Metadata } from "next";
import { AuthShell } from "@/components/auth/AuthShell";
import { VerifyEmailForm } from "@/components/auth/VerifyEmailForm";

// Server component (statically prerendered) so it can own page metadata; the interactive
// code entry lives in the "use client" <VerifyEmailForm />. Shares AuthShell with the other auth pages.
export const metadata: Metadata = {
  title: "Verify email — In-Between Co-pilot",
  description: "Confirm your email with the code we sent you.",
};

export default function VerifyEmailPage() {
  return (
    <AuthShell
      title="Verify your email"
      description="Enter the 6-digit code we sent to your email address."
    >
      <VerifyEmailForm />
    </AuthShell>
  );
}
