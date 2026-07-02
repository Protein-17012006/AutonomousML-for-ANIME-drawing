"use client";
import dynamic from "next/dynamic";

// The co-pilot is a client-only SPA (SSE streaming + useLayoutEffect DOM
// measurement). Render client-side only to avoid SSR/hydration mismatches —
// it was never designed to server-render.
const CopilotApp = dynamic(() => import("@/components/copilot/CopilotApp"), {
  ssr: false,
});

export default function CopilotPage() {
  return <CopilotApp />;
}
