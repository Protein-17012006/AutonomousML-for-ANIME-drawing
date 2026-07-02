"use client";
import { useEffect } from "react";

// Front door → the chat-first In-Between Co-pilot. Client-side redirect so it works
// both in dev and in the static export served by the box (a server redirect() is not
// compatible with `output: export`). The stub chat landing was removed.
export default function Home() {
  useEffect(() => {
    window.location.replace("/copilot");
  }, []);
  return null;
}
