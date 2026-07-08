import type { Metadata } from "next";
import { AuthShell } from "@/components/auth/AuthShell";
import { LoginForm } from "@/components/auth/LoginForm";

// Server component (statically prerendered) so it can own page metadata; the interactive
// form lives in the "use client" <LoginForm />.
export const metadata: Metadata = {
  title: "Sign in — In-Between Co-pilot",
  description: "Sign in to your In-Between Co-pilot workspace.",
};

export default function LoginPage() {
  return (
    <AuthShell
      title="Welcome back"
      description="Sign in to pick up your in-between sessions."
    >
      <LoginForm />
    </AuthShell>
  );
}
