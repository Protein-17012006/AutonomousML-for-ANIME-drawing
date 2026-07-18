"use client";

import type { ReactNode } from "react";
import { configureAmplify } from "@/lib/amplify";

export function AmplifyBoot({ children }: { children: ReactNode }) {
  configureAmplify();

  return <>{children}</>;
}
