import { LoaderCircle, TriangleAlert } from "lucide-react";
import { ChatTextBubble } from "./ChatTextBubble";

export function QaMessage({
  question,
  answer,
  grounded,
}: {
  question: string;
  answer: string | null;
  grounded?: boolean;
}) {
  return (
    <div className="qa-turn">
      <ChatTextBubble tone="user">{question}</ChatTextBubble>
      <ChatTextBubble tone="agent">
        {answer === null ? (
          <span className="chat-pulse">
            <LoaderCircle
              className="mr-1 inline size-3 animate-spin"
              aria-hidden="true"
            />
            thinking…
          </span>
        ) : (
          <>
            {grounded === false && (
              <span
                className="qa-offline"
                title="LLM offline — deterministic summary"
              >
                <TriangleAlert
                  className="mr-1 inline size-3.5"
                  aria-hidden="true"
                />
              </span>
            )}
            {answer}
          </>
        )}
      </ChatTextBubble>
    </div>
  );
}
