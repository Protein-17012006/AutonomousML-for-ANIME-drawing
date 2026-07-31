// Chat transcript — renders the derived ChatMsg list (vault 'Chat-First Copilot Surface' §1-2).
import { useEffect, useRef } from "react";
import type { ResultEvent } from "../../types";
import type { ChatMsg } from "../../lib/chatModel";
import { ErrorMessage } from "./ErrorMessage";
import { ProgressMessage } from "./ProgressMessage";
import { QaMessage } from "./QaMessage";
import { ResultCard } from "./ResultCard";
import { UploadMessage } from "./UploadMessage";

export function ChatView({
  msgs,
  keyUrls,
  onOpenBoard,
  onExport,
}: {
  msgs: ChatMsg[];
  keyUrls: string[];
  onOpenBoard: () => void;
  onExport: (result: ResultEvent) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [msgs.length]);

  return (
    <div className="chat-thread" role="log" aria-label="Co-pilot conversation">
      {msgs.map((m) => {
        switch (m.kind) {
          
          case "user-upload":
            return <UploadMessage key={m.id} text={m.text} />;
          
          case "progress":
            return (
              <ProgressMessage
                key={m.id}
                done={m.done}
                running={m.running}
              />
            );
           
          case "result":
            return (
              <ResultCard
                key={m.id}
                result={m.result}
                keyUrls={keyUrls}
                onOpenBoard={onOpenBoard}
                onExport={onExport}
              />
            );
          
          case "qa":
            return (
              <QaMessage
                key={m.id}
                question={m.q}
                answer={m.answer}
                grounded={m.grounded}
              />
            );
            
          case "error":
            return <ErrorMessage key={m.id} text={m.text} />;
        }
      })}
      <div ref={endRef} />
    </div>
  );
}
