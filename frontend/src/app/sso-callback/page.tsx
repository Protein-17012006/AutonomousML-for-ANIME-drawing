"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Hub } from "aws-amplify/utils";
import { configureAmplify } from "@/lib/amplify";
import { establishCookieSession } from "@/lib/authenticatedApi";

export default function SsoCallbackPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Finishing sign in...");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    configureAmplify();
    let active = true;
    let finishing = false;
    const finish = async () => {
      if (finishing) return;
      finishing = true;
      let lastError: unknown;
      for (let attempt = 0; attempt < 20 && active; attempt += 1) {
        try {
          await establishCookieSession();
          if (active) router.replace("/copilot");
          return;
        } catch (error) {
          lastError = error;
          // The OAuth listener exchanges Cognito's code asynchronously after
          // a full-page redirect. Wait briefly for tokens instead of treating
          // the first token lookup as a completed authentication failure.
          await new Promise((resolve) => window.setTimeout(resolve, 250));
        }
      }
      finishing = false;
      if (active) {
        setFailed(true);
        setMessage(
          lastError instanceof Error
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
  }, [router]);

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
      </div>
    </main>
  );
}
