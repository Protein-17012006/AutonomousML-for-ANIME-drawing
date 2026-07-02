import type { Metadata } from "next";
import type { ReactNode } from "react";
// Self-contained animation-desk / timing-sheet stylesheet (ported from the team's
// Vite SPA `frontend/src/index.css`). Loaded only for the /copilot segment so its
// global `body`/`@theme` rules don't touch the chat landing.
import "./copilot.css";

export const metadata: Metadata = {
  title: "In-Between Co-pilot",
  description:
    "Anime in-between QA co-pilot — gate → interpolate → calibrated self-QA → correction loop.",
};

// No wrapper node: the ported SPA's root is `<div className="app">` and its CSS
// expects `.app` to be a direct child of a height:100% body (copilot.css sets that).
export default function CopilotLayout({ children }: { children: ReactNode }) {
  return children;
}
