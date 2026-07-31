"use client";

import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getCookieSession, isAuthRequestError } from "@/lib/authenticatedApi";

interface AuthPageGuardProps {
  children: ReactNode;
}

type AuthPageAvailability = "available" | "unavailable";
const AuthPageAvailabilityContext = createContext<AuthPageAvailability>("available");

export function useAuthPageAvailability() {
  return useContext(AuthPageAvailabilityContext);
}

export function AuthPageGuard({ children }: AuthPageGuardProps) {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [availability, setAvailability] = useState<AuthPageAvailability>("available");

  useEffect(() => {
    let active = true;

    async function redirectSignedInUser() {
      try {
        await getCookieSession();
        if (active) router.replace("/copilot");
      } catch (error) {
        // A missing, expired, or unavailable cookie session must not prevent
        // the user from reaching the page where they can authenticate.
        if (active) {
          if (isAuthRequestError(error, "unavailable")) {
            setAvailability("unavailable");
          }
          setChecking(false);
        }
      }
    }

    void redirectSignedInUser();

    return () => {
      active = false;
    };
  }, [router]);

  if (checking) {
    return (
      <main className="grid min-h-screen place-items-center bg-sumi text-washi">
        <p role="status" className="font-body text-sm text-ash">
          Checking session...
        </p>
      </main>
    );
  }

  return (
    <AuthPageAvailabilityContext.Provider value={availability}>
      {children}
    </AuthPageAvailabilityContext.Provider>
  );
}
