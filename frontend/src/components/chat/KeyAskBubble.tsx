// The agent ASKS for a key: needs_key / abstain rendered as a question with an
// inline reply dropzone (the collaborative-loop turn made conversational).
import { useRef, useState } from "react";
import type { PairEvent } from "../../types";

export function KeyAskBubble({ pair, resolved, onRefill }: {
  pair: PairEvent;
  resolved: boolean;
  onRefill: (index: number, file: File) => Promise<void>;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const isGap = pair.action === "needs_key";
  const text = isGap
    ? `Gap ${pair.index} is too wide to interpolate safely — can you draw me one breakdown key?`
    : `I'm not sure about pair ${pair.index} (${pair.reason || "uncertain"}) — a key here would settle it.`;
  const send = async (f: File | null) => {
    if (!f || busy) return;
    setBusy(true);
    try { await onRefill(pair.index, f); } finally { setBusy(false); }
  };
  return (
    <div className={`bubble agent ask${resolved ? " resolved" : ""}`}>
      <div className="bubble-label">{isGap ? "🔑 Key requested" : "🤔 Unsure — key welcome"}</div>
      <p>{text}</p>
      {!resolved && (
        <>
          <input ref={inputRef} type="file" accept="image/png" className="visually-hidden"
            onChange={(e) => { const f = e.currentTarget.files?.[0] ?? null; e.currentTarget.value = ""; void send(f); }} />
          <button type="button" className="btn btn-primary" disabled={busy}
            onClick={() => inputRef.current?.click()}>
            {busy ? "Splicing…" : "Upload a key PNG"}
          </button>
        </>
      )}
    </div>
  );
}
