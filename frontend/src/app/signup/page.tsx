import type { Metadata } from "next";
import { AuthShell } from "@/components/auth/AuthShell";
import { SignupForm } from "@/components/auth/SignupForm";

// Server component (statically prerendered) so it can own page metadata; the interactive
// form lives in the "use client" <SignupForm />.
export const metadata: Metadata = {
  title: "Create account — In-Between Co-pilot",
  description: "Create your In-Between Co-pilot account.",
};

export default function SignupPage() {
  return (
    <AuthShell
      title="Create your account"
      description="Start filling and verifying your in-betweens."
    >
      <SignupForm />
    </AuthShell>
  );
}
