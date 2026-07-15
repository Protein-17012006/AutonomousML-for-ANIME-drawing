"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Hub } from "aws-amplify/utils";
import { getCurrentUser } from "aws-amplify/auth";
import { configureAmplify } from "@/lib/amplify";

export default function SsoCallbackPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Finishing sign in...");

  useEffect(() => {
    configureAmplify();
    let active = true;
    const stop = Hub.listen("auth", ({ payload }) => {
      if (payload.event === "signedIn") router.replace("/copilot");
      if (payload.event === "signInWithRedirect_failure") {
        setMessage("Sign in failed. Return to login and try again.");
      }
    });

    getCurrentUser()
      .then(() => {
        if (active) router.replace("/copilot");
      })
      .catch(() => {
        if (active) setMessage("Finishing sign in...");
      });

    return () => {
      active = false;
      stop();
    };
  }, [router]);

  return (
    <main className="grid min-h-screen place-items-center bg-background text-foreground">
      <p className="text-sm text-muted-foreground">{message}</p>
    </main>
  );
}
