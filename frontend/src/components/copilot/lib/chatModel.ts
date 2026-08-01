// Chat message derivation — PURE (vault 'Chat-First Copilot Surface' §1).
// Derives the conversation from App state on each render instead of reducing SSE
// events incrementally: the draw-key splice REPLACES the whole log, which an
// incremental reducer cannot survive but a derive-function handles for free.
import type { PairEvent, ResultEvent } from "../types";
import type { AgentAction } from "../api";

export type ChatMsg =
  | { kind: "user-upload"; id: string; text: string }
  | {
      kind: "progress";
      id: string;
      done: number;
      running: boolean;
    }
  | { kind: "result"; id: string; result: ResultEvent }
  | {
      kind: "qa";
      id: string;
      q: string;
      answer: string | null;
      grounded?: boolean;
      action?: AgentAction | null;
      actionDone?: boolean;
      actionNote?: string | null;
      rejectedTool?: string;
      followups?: string[];
    }
  | { kind: "error"; id: string; text: string };

export interface UserTurn {
  media: "keyframes" | "video";
  count: number;
}
export interface QaTurn {
  q: string;
  answer: string | null;
  grounded?: boolean;
  /** The one tool the agent proposed this turn, if any. Nothing has run: it is
   *  waiting on the artist, which is the whole contract. */
  action?: AgentAction | null;
  /** Set once the artist accepted it, so the card stops offering a second run. */
  actionDone?: boolean;
  /** What the server said when the action was carried out, or why it failed. */
  actionNote?: string | null;
  /** The model named a tool the server refused. Its prose may still describe
   *  that action, so this is shown rather than swallowed. */
  rejectedTool?: string;
  followups?: string[];
}

export function deriveMessages(i: {
  upload: UserTurn | null;
  log: PairEvent[];
  result: ResultEvent | null;
  running: boolean;
  banner: string | null;
  qa: QaTurn[];
}): ChatMsg[] {
  const out: ChatMsg[] = [];
  if (i.upload) {
    const text =
      i.upload.media === "video"
        ? "1 video sent — please analyze the media."
        : `${i.upload.count} keyframe${i.upload.count === 1 ? "" : "s"} sent — please analyze the media.`;
    out.push({ kind: "user-upload", id: "up", text });
  }

  if (i.log.length || i.running)
    out.push({
      kind: "progress",
      id: "prog",
      done: i.log.length,
      running: i.running,
    });

  if (i.result?.qa_degraded)
    out.push({
      kind: "error",
      id: "degraded",
      text: "The QA model was unreachable — verdicts degraded to softness/gate signals.",
    });

  if (i.result) out.push({ kind: "result", id: "res", result: i.result });

  i.qa.forEach((t, n) => out.push({ kind: "qa", id: `qa-${n}`, ...t }));

  if (i.banner) out.push({ kind: "error", id: "err", text: i.banner });
  return out;
}
