"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getCookieSession } from "@/lib/authenticatedApi";

const CopilotApp = dynamic(() => import("@/components/copilot/CopilotApp"), {
  ssr: false,
});

export default function CopilotPage() {
  const router = useRouter();
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    let active = true;
    getCookieSession()
      .then(() => {
        if (active) {
          setAllowed(true);
        }
      })
      .catch(() => {
        if (active) router.replace("/login");
      });
    return () => {
      active = false;
    };
  }, [router]);

  if (!allowed) {
    return (
      <main className="grid min-h-screen place-items-center bg-background text-foreground">
        <p role="status" className="text-sm text-muted-foreground">
          Checking your session...
        </p>
      </main>
    );
  }
  return <CopilotApp />;
}
