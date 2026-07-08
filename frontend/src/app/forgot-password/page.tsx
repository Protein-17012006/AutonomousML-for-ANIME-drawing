import type { Metadata } from "next";
import { AuthShell } from "@/components/auth/AuthShell";
import { ForgotPasswordForm } from "@/components/auth/ForgotPasswordForm";

// Server component (statically prerendered) so it can own page metadata; the interactive
// form lives in the "use client" <ForgotPasswordForm />. Shares the same AuthShell as /login + /signup.
export const metadata: Metadata = {
  title: "Reset password — In-Between Co-pilot",
  description: "Reset your In-Between Co-pilot password.",
};

export default function ForgotPasswordPage() {
  return (
    <AuthShell
      title="Reset your password"
      description="Enter the email linked to your account and we'll send you a reset link."
    >
      <ForgotPasswordForm />
    </AuthShell>
  );
}
