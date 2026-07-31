"use client";

import type { ReactNode } from "react";
import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { type AuthFlowIntent, readAuthFlow } from "@/lib/authFlow";

export function AuthFlowGuard({
  intent,
  fallback,
  children,
}: {
  intent: AuthFlowIntent;
  fallback: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const flow = useSyncExternalStore(
    () => () => undefined,
    readAuthFlow,
    () => null,
  );
  const allowed = flow?.intent === intent;

  useEffect(() => {
    if (!allowed) {
      router.replace(fallback);
    }
  }, [allowed, fallback, router]);

  if (!allowed) {
    return (
      <p role="status" className="text-center text-sm text-ash">
        Checking sign-in step...
      </p>
    );
  }
  return children;
}
