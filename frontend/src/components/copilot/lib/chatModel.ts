// Chat message derivation — PURE (vault 'Chat-First Copilot Surface' §1).
// Derives the conversation from App state on each render instead of reducing SSE
// events incrementally: the draw-key splice REPLACES the whole log, which an
// incremental reducer cannot survive but a derive-function handles for free.
import type { Explanation, PairEvent, ResultEvent } from "../types";

export type ChatMsg =
  | { kind: "user-upload"; id: string; label: string; thumbs: string[] }
  | { kind: "progress"; id: string; done: number; total: number | null; passes: PairEvent[]; running: boolean }
  | { kind: "flag"; id: string; pair: PairEvent; ex?: Explanation }
  | { kind: "ask-key"; id: string; pair: PairEvent; resolved: boolean }
  | { kind: "warning"; id: string; text: string }
  | { kind: "result"; id: string; result: ResultEvent }
  | { kind: "qa"; id: string; q: string; answer: string | null; grounded?: boolean }
  | { kind: "error"; id: string; text: string };

export interface UserTurn { label: string; thumbs: string[] }
export interface QaTurn { q: string; answer: string | null; grounded?: boolean }

export function deriveMessages(i: {
  upload: UserTurn | null;
  log: PairEvent[];
  result: ResultEvent | null;
  running: boolean;
  banner: string | null;
  qa: QaTurn[];
}): ChatMsg[] {
  const out: ChatMsg[] = [];
  if (i.upload) out.push({ kind: "user-upload", id: "up", ...i.upload });

  const passes = i.log.filter((p) => p.qa === "pass");
  if (i.log.length || i.running)
    out.push({
      kind: "progress", id: "prog", done: i.log.length,
      total: i.result ? i.log.length : null, passes, running: i.running,
    });

  for (const p of i.log) {
    const ex = i.result?.explanations?.[String(p.index)];
    if (p.qa === "flag") {
      out.push({ kind: "flag", id: `flag-${p.index}`, pair: p, ex });
    } else if (p.action === "needs_key" || p.qa === "abstain") {
      out.push({
        kind: "ask-key", id: `ask-${p.index}`, pair: p,
        resolved: p.action !== "needs_key" && p.qa !== "abstain",
      });
    }
  }

  if (i.result?.qa_degraded)
    out.push({
      kind: "warning", id: "degraded",
      text: "The QA model was unreachable — verdicts degraded to softness/gate signals.",
    });
  if (i.result) out.push({ kind: "result", id: "res", result: i.result });
  i.qa.forEach((t, n) => out.push({ kind: "qa", id: `qa-${n}`, ...t }));
  if (i.banner) out.push({ kind: "error", id: "err", text: i.banner });
  return out;
}
