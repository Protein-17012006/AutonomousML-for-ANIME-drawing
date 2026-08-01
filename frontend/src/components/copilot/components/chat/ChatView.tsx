// Chat transcript — renders the derived ChatMsg list (vault 'Chat-First Copilot Surface' §1-2).
import { useEffect, useRef } from "react";
import type { ResultEvent } from "../../types";
import type { ChatMsg } from "../../lib/chatModel";
import { ErrorMessage } from "./ErrorMessage";
import { ProgressMessage } from "./ProgressMessage";
import { QaMessage } from "./QaMessage";
import { AgentActionBubble } from "./AgentActionBubble";
import { ResultCard } from "./ResultCard";
import { UploadMessage } from "./UploadMessage";

export function ChatView({
  msgs,
  keyUrls,
  onOpenBoard,
  onExport,
  onAcceptAction,
  onDismissAction,
  actionBusy,
}: {
  msgs: ChatMsg[];
  keyUrls: string[];
  onOpenBoard: () => void;
  onExport: (result: ResultEvent) => void;
  onAcceptAction: (turn: number) => void;
  onDismissAction: (turn: number) => void;
  actionBusy?: boolean;
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
          
          case "qa": {
            // `qa-<n>` is the turn's index in the qa list; the accept handler
            // needs it to update the right turn.
            const turn = Number(m.id.slice(3));
            return (
              <div key={m.id}>
                <QaMessage
                  question={m.q}
                  answer={m.answer}
                  grounded={m.grounded}
                />
                <AgentActionBubble
                  action={m.action}
                  done={m.actionDone}
                  note={m.actionNote}
                  rejectedTool={m.rejectedTool}
                  busy={actionBusy}
                  onAccept={() => onAcceptAction(turn)}
                  onDismiss={() => onDismissAction(turn)}
                />
              </div>
            );
          }
            
          case "error":
            return <ErrorMessage key={m.id} text={m.text} />;
        }
      })}
      <div ref={endRef} />
    </div>
  );
}
