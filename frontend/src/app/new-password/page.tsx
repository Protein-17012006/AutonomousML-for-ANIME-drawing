import type { Metadata } from "next";
import { AuthFlowGuard } from "@/components/auth/AuthFlowGuard";
import { AuthShell } from "@/components/auth/AuthShell";
import { NewPasswordForm } from "@/components/auth/NewPasswordForm";

export const metadata: Metadata = {
  title: "Set a new password — In-Between Co-pilot",
  description: "Complete the password change required before signing in.",
};

export default function NewPasswordPage() {
  return (
    <AuthFlowGuard intent="new-password" fallback="/login">
      <AuthShell
        title="Set a new password"
        description="Your account requires a new password before you can continue."
      >
        <NewPasswordForm />
      </AuthShell>
    </AuthFlowGuard>
  );
}
