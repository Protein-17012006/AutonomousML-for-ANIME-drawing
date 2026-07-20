// Chat transcript — renders the derived ChatMsg list (vault 'Chat-First Copilot Surface' §1-2).
import { useEffect, useRef } from "react";
import type { ResultEvent } from "../../types";
import type { ChatMsg } from "../../lib/chatModel";
import { FlagBubble } from "./FlagBubble";
import { KeyAskBubble } from "./KeyAskBubble";
import { ResultCard } from "./ResultCard";
import { Check, LoaderCircle, TriangleAlert } from "lucide-react";

/* eslint-disable @next/next/no-img-element -- streamed previews are browser-local URLs. */

export function ChatView({
  msgs,
  keyUrls,
  onOpenBoard,
  onRefill,
  onExport,
}: {
  msgs: ChatMsg[];
  keyUrls: string[];
  onOpenBoard: (focus: number | null) => void;
  onRefill: (index: number, file: File) => Promise<void>;
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
            return (
              <div key={m.id} className="bubble user">
                <div className="bubble-label">{m.label}</div>
                {m.thumbs.length > 0 && (
                  <div className="bubble-thumbs">
                    {m.thumbs.map((u, i) => (
                      <img key={i} src={u} alt="" draggable={false} />
                    ))}
                  </div>
                )}
              </div>
            );
          
          case "progress":
            return (
              <div key={m.id} className="bubble agent">
                <div className="bubble-label">
                  {m.running
                    ? `Filling & checking… ${m.done} pair${m.done === 1 ? "" : "s"} so far`
                    : `Checked ${m.done} pair${m.done === 1 ? "" : "s"}`}
                  {m.running && (
                    <span className="chat-pulse" aria-hidden="true">
                      <LoaderCircle className="inline size-3 animate-spin" aria-hidden="true" />
                    </span>
                  )}
                </div>
                {m.passes.length > 0 && (
                  <div className="chip-row">
                    {m.passes.map((p) => (
                      <span
                        key={p.index}
                        className="chip chip-pass"
                        title={p.route ?? ""}
                      >
                        <Check className="mr-1 inline size-3" aria-hidden="true" /> {p.index}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
           
          case "flag":
            return (
              <FlagBubble
                key={m.id}
                pair={m.pair}
                ex={m.ex}
                keyUrls={keyUrls}
                onReview={() => onOpenBoard(m.pair.index)}
              />
            );
           
          case "ask-key":
            return (
              <KeyAskBubble
                key={m.id}
                pair={m.pair}
                resolved={m.resolved}
                onRefill={onRefill}
              />
            );
             
          case "warning":
            return (
              <div key={m.id} className="bubble agent warn">
                {m.text}
              </div>
            );
           
          case "result":
            return (
              <ResultCard
                key={m.id}
                result={m.result}
                keyUrls={keyUrls}
                onOpenBoard={() => onOpenBoard(null)}
                onExport={onExport}
              />
            );
          
          case "qa":
            return (
              <div key={m.id} className="qa-turn">
                <div className="bubble user">{m.q}</div>
                <div className="bubble agent">
                  {m.answer === null ? (
                    <span className="chat-pulse">
                      <LoaderCircle className="mr-1 inline size-3 animate-spin" aria-hidden="true" />
                      thinking…
                    </span>
                  ) : (
                    <>
                      {m.grounded === false && (
                        <span
                          className="qa-offline"
                          title="LLM offline — deterministic summary"
                        >
                          <TriangleAlert className="mr-1 inline size-3.5" aria-hidden="true" />
                        </span>
                      )}
                      {m.answer}
                    </>
                  )}
                </div>
              </div>
            );
            
          case "error":
            return (
              <div key={m.id} className="bubble agent err">
                {m.text}
              </div>
            );
        }
      })}
      <div ref={endRef} />
    </div>
  );
}
