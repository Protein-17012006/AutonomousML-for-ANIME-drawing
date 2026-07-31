import type { ReactNode } from "react";

export function ChatTextBubble({
  tone,
  children,
}: {
  tone: "user" | "agent" | "error";
  children: ReactNode;
}) {
  return (
    <div className={`bubble ${tone === "error" ? "agent err" : tone}`}>
      {children}
    </div>
  );
}
