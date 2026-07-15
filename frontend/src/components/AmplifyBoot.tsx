"use client";

import { useEffect, type ReactNode } from "react";
import { configureAmplify } from "@/lib/amplify";

export function AmplifyBoot({ children }: { children: ReactNode }) {
  useEffect(() => {
    configureAmplify();
  }, []);

  return <>{children}</>;
}
