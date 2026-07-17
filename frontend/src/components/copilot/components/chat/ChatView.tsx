// Chat transcript — renders the derived ChatMsg list (vault 'Chat-First Copilot Surface' §1-2).
import { useEffect, useRef } from "react";
import type { ResultEvent } from "../../types";
import type { ChatMsg } from "../../lib/chatModel";
import { FlagBubble } from "./FlagBubble";
import { KeyAskBubble } from "./KeyAskBubble";
import { ResultCard } from "./ResultCard";

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
  // follow the conversation as bubbles stream in (like any chat client)
  useEffect(() => {
    // Pair events arrive in quick succession over SSE; instant scrolling avoids
    // queuing a separate smooth-scroll animation for every event.
    endRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [msgs.length]);

  return (
    <div className="chat-thread" role="log" aria-label="Co-pilot conversation">
      {msgs.map((m) => {
        switch (m.kind) {
          // Case: User Upload
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
            // Case: Progress
          case "progress":
            return (
              <div key={m.id} className="bubble agent">
                <div className="bubble-label">
                  {m.running
                    ? `Filling & checking… ${m.done} pair${m.done === 1 ? "" : "s"} so far`
                    : `Checked ${m.done} pair${m.done === 1 ? "" : "s"}`}
                  {m.running && (
                    <span className="chat-pulse" aria-hidden="true">
                      ▮
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
                        ✓ {p.index}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
            // Case: Flag
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
             // Case: Ask for Key
          case "ask-key":
            return (
              <KeyAskBubble
                key={m.id}
                pair={m.pair}
                resolved={m.resolved}
                onRefill={onRefill}
              />
            );
             // Case: Warning
          case "warning":
            return (
              <div key={m.id} className="bubble agent warn">
                {m.text}
              </div>
            );
             // Case: Flag
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
             // Case: QA
          case "qa":
            return (
              <div key={m.id} className="qa-turn">
                <div className="bubble user">{m.q}</div>
                <div className="bubble agent">
                  {m.answer === null ? (
                    <span className="chat-pulse">thinking…</span>
                  ) : (
                    <>
                      {m.grounded === false && (
                        <span
                          className="qa-offline"
                          title="LLM offline — deterministic summary"
                        >
                          ⚠{" "}
                        </span>
                      )}
                      {m.answer}
                    </>
                  )}
                </div>
              </div>
            );
             // Case: Error
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
