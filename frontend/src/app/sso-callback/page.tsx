"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Hub } from "aws-amplify/utils";
import { Button } from "@/components/ui/button";
import { configureAmplify, getCurrentIdToken } from "@/lib/amplify";
import { establishCookieSession, isAuthRequestError } from "@/lib/authenticatedApi";

const SSO_TOTAL_TIMEOUT_MS = 10_000;

export default function SsoCallbackPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Finishing sign in...");
  const [failed, setFailed] = useState(false);
  const [retryable, setRetryable] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    configureAmplify();
    let active = true;
    let finishing = false;
    const finish = async () => {
      if (finishing) return;
      finishing = true;
      let lastError: unknown;
      const deadline = Date.now() + SSO_TOTAL_TIMEOUT_MS;
      for (; active && Date.now() < deadline;) {
        try {
          await establishCookieSession(Math.max(1, deadline - Date.now()));
          if (active) router.replace("/copilot");
          return;
        } catch (error) {
          lastError = error;
          if (isAuthRequestError(error, "unavailable")) break;
          // The OAuth listener exchanges Cognito's code asynchronously after
          // a full-page redirect. Wait briefly for tokens instead of treating
          // the first token lookup as a completed authentication failure.
          await new Promise((resolve) => window.setTimeout(resolve, 250));
        }
      }
      finishing = false;
      if (active) {
        let hasToken = false;
        try {
          await getCurrentIdToken();
          hasToken = true;
        } catch {
          hasToken = false;
        }
        setRetryable(hasToken && isAuthRequestError(lastError, "unavailable"));
        setFailed(!hasToken || !isAuthRequestError(lastError, "unavailable"));
        setMessage(
          hasToken && isAuthRequestError(lastError, "unavailable")
            ? "Cognito sign-in succeeded, but the co-pilot service is temporarily unavailable."
            : lastError instanceof Error
            ? lastError.message
            : "Sign in failed. Return to login and try again.",
        );
      }
    };
    const stop = Hub.listen("auth", ({ payload }) => {
      if (payload.event === "signedIn") void finish();
      if (payload.event === "signInWithRedirect_failure") {
        setFailed(true);
        setMessage("Sign in failed. Return to login and try again.");
      }
    });

    void finish();

    return () => {
      active = false;
      stop();
    };
  }, [retryCount, router]);

  function retry() {
    setFailed(false);
    setRetryable(false);
    setMessage("Finishing sign in...");
    setRetryCount((count) => count + 1);
  }

  return (
    <main className="grid min-h-screen place-items-center bg-background text-foreground">
      <div className="flex flex-col items-center gap-4 text-center">
        <p role={failed ? "alert" : "status"} className="text-sm text-muted-foreground">
          {message}
        </p>
        {failed && (
          <Link href="/login" className="text-sm font-medium underline underline-offset-4">
            Return to login
          </Link>
        )}
        {retryable && (
          <Button type="button" variant="link" onClick={retry}>
            Retry
          </Button>
        )}
      </div>
    </main>
  );
}
