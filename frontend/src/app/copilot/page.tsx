"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { getCookieSession, isAuthRequestError } from "@/lib/authenticatedApi";

const CopilotApp = dynamic(() => import("@/components/copilot/CopilotApp"), {
  ssr: false,
});

export default function CopilotPage() {
  const router = useRouter();
  const [state, setState] = useState<"checking" | "allowed" | "unavailable">("checking");

  const checkSession = useCallback(() => {
    setState("checking");
    void getCookieSession()
      .then(() => setState("allowed"))
      .catch((error: unknown) => {
        if (isAuthRequestError(error, "unauthenticated")) {
          router.replace("/login");
        } else {
          setState("unavailable");
        }
      });
  }, [router]);

  useEffect(() => {
    let active = true;
    void getCookieSession()
      .then(() => {
        if (active) setState("allowed");
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (isAuthRequestError(error, "unauthenticated")) {
          router.replace("/login");
        } else {
          setState("unavailable");
        }
      });
    return () => {
      active = false;
    };
  }, [router]);

  if (state !== "allowed") {
    return (
      <main className="grid min-h-screen place-items-center bg-background text-foreground">
        {state === "unavailable" ? (
          <div className="flex flex-col items-center gap-3 text-center">
            <p role="alert" className="text-sm text-muted-foreground">
              The co-pilot service is temporarily unavailable.
            </p>
            <div className="flex items-center gap-2">
              <Button type="button" variant="link" onClick={() => void checkSession()}>
                Retry
              </Button>
              <Button type="button" variant="link" onClick={() => router.replace("/login")}>
                Return to login
              </Button>
            </div>
          </div>
        ) : (
          <p role="status" className="text-sm text-muted-foreground">
            Checking your session...
          </p>
        )}
      </main>
    );
  }
  return <CopilotApp />;
}
