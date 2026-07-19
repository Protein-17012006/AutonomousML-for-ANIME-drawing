// The agent ASKS for a key: needs_key / abstain rendered as a question with an
// inline reply dropzone (the collaborative-loop turn made conversational).
import { useRef, useState } from "react";
import type { PairEvent } from "../../types";
import { Button } from "@/components/ui/button";
import { CircleHelp, KeyRound, Upload } from "lucide-react";

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
      <div className="bubble-label">
        {isGap ? <KeyRound className="mr-1 inline size-3.5" aria-hidden="true" /> : <CircleHelp className="mr-1 inline size-3.5" aria-hidden="true" />}
        {isGap ? "Key requested" : "Unsure — a key could settle this"}
      </div>
      <p>{text}</p>
      {!resolved && (
        <>
          <input ref={inputRef} type="file" accept="image/png" className="sr-only"
            onChange={(e) => { const f = e.currentTarget.files?.[0] ?? null; e.currentTarget.value = ""; void send(f); }} />
          <Button type="button" className="border-ao bg-ao font-mono text-[12.5px] font-semibold tracking-[0.02em] text-on-ao hover:bg-ao/85" disabled={busy}
            onClick={() => inputRef.current?.click()}>
            {busy ? "Splicing…" : <><Upload className="size-3.5" aria-hidden="true" /> Upload a key PNG</>}
          </Button>
        </>
      )}
    </div>
  );
}
