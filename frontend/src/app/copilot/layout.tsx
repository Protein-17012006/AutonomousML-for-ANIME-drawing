import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./copilot.css";

export const metadata: Metadata = {
  title: "In-Between Co-pilot",
  description:
    "Anime in-between QA co-pilot — gate → interpolate → calibrated self-QA → correction loop.",
};

export default function CopilotLayout({ children }: { children: ReactNode }) {
  return children;
}
