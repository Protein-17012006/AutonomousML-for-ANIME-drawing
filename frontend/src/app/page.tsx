import type { Metadata } from "next";
import { HomePage } from "@/components/landing/HomePage";

// Landing / front door. Server component (statically prerendered in the export build) that owns
// the page metadata and delegates the whole layout to <HomePage />.
export const metadata: Metadata = {
  title: "In-Between Co-pilot — Anime in-betweens, verified",
  description:
    "Draw the keys. The co-pilot fills the in-between frames and runs calibrated self-QA on every one — so nothing off-model, flickering, or morphed ever ships.",
};

export default function Home() {
  return <HomePage />;
}
