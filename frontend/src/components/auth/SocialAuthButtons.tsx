"use client";

import { useState } from "react";
import { signInWithRedirect } from "aws-amplify/auth";
import { Button } from "@/components/ui/button";
import { GoogleIcon } from "@/components/common/icons/GoogleIcon";
import { GitHubIcon } from "@/components/common/icons/GitHubIcon";
import { AppleIcon } from "@/components/common/icons/AppleIcon";
import { configureAmplify } from "@/lib/amplify";

const PROVIDERS = [
  { name: "Google", Icon: GoogleIcon, enabled: true },
  { name: "GitHub", Icon: GitHubIcon, enabled: false },
  { name: "Apple", Icon: AppleIcon, enabled: false },
] as const;

export function SocialAuthButtons() {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function googleSignIn() {
    configureAmplify();
    setError(null);
    setSubmitting(true);
    try {
      await signInWithRedirect({ provider: "Google" });
    } catch (err) {
      setSubmitting(false);
      setError(err instanceof Error ? err.message : "Could not continue with Google.");
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {PROVIDERS.map(({ name, Icon, enabled }) => (
        <Button
          key={name}
          type="button"
          variant="outline"
          disabled={!enabled || submitting}
          onClick={enabled ? googleSignIn : undefined}
          className="h-10 w-full justify-center gap-2"
        >
          <Icon className="size-4" />
          Continue with {name}
          {!enabled && <span className="text-xs text-muted-foreground">(coming soon)</span>}
        </Button>
      ))}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
