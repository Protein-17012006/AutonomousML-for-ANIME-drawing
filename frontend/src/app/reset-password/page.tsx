import type { Metadata } from "next";
import { AuthShell } from "@/components/auth/AuthShell";
import { ResetPasswordForm } from "@/components/auth/ResetPasswordForm";
import { AuthFlowGuard } from "@/components/auth/AuthFlowGuard";

// Server component (statically prerendered) so it can own page metadata; the interactive
// form lives in the "use client" <ResetPasswordForm />. Shares AuthShell with the other auth pages.
export const metadata: Metadata = {
  title: "Set a new password — In-Between Co-pilot",
  description: "Choose a new password for your In-Between Co-pilot account.",
};

export default function ResetPasswordPage() {
  return (
    <AuthFlowGuard intent="reset-password" fallback="/login">
      <AuthShell
        title="Set a new password"
        description="Choose a new password for your account."
      >
        <ResetPasswordForm />
      </AuthShell>
    </AuthFlowGuard>
  );
}
