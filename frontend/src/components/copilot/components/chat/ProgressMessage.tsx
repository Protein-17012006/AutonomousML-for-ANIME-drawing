import { LoaderCircle } from "lucide-react";
import { ChatTextBubble } from "./ChatTextBubble";

export function ProgressMessage({
  done,
  running,
}: {
  done: number;
  running: boolean;
}) {
  return (
    <ChatTextBubble tone="agent">
      Processed {done} pair{done === 1 ? "" : "s"}
      {running && (
        <span className="chat-pulse" aria-hidden="true">
          <LoaderCircle className="inline size-3 animate-spin" />
        </span>
      )}
    </ChatTextBubble>
  );
}
