"use client";

// The planner's conversation, shown as it happens.
//
// Without this the artist waits at a spinner while several agents talk, and the
// only thing they ever see is the summary at the end — which is exactly the
// part that reads like a single model making claims. The value of the
// orchestration layer is that a specialist can REFUSE, and a refusal is only
// worth anything if the person can see who refused and why.

import { cn } from "@/lib/utils";
import type { TranscriptEntry } from "../../api";

/** The agents by their own names — the artist should see who answered. */
const SPEAKER: Record<string, string> = {
  orchestrator: "Planner",
  triage: "Triage",
  perception: "Perception",
  qa_csq: "QA",
  // Not an agent: the check that reads the finished reply back against what the
  // steps actually reported. It speaks only when it caught something, and what
  // it caught is the artist's business.
  verifier: "Check",
};

function speaker(name: string): string {
  return SPEAKER[name] ?? name;
}

/** What the planner said when it chose not to open a plan, in the artist's terms. */
const PLAN_REASON: Record<string, string> = {
  "planner judged this needs no specialist step":
    "The planner answered this one directly — no specialist was needed.",
  "planner named no registered target":
    "The planner asked for a specialist this build does not have, so it answered directly.",
  "planner unavailable (no LLM configured)":
    "The planner is offline, so this was answered directly.",
};

function planNote(reason: string): string {
  return (
    PLAN_REASON[reason] ??
    (reason.startsWith("planner call failed")
      ? "The planner could not be reached, so this was answered directly."
      : `The planner answered directly (${reason}).`)
  );
}

export function AgentTranscript({
  entries,
  running,
  orchestrated,
  planReason,
}: {
  entries: TranscriptEntry[];
  running: boolean;
  /** Planned turns only: whether specialists were actually consulted. */
  orchestrated?: boolean;
  planReason?: string;
}) {
  // An empty transcript used to render nothing, which made a planner that
  // DECLINED look exactly like a planner that was never asked. On a build whose
  // selling point is that specialists can refuse, silence is the one thing this
  // must not do — so a declined plan says so, and says why.
  const declined = !running && entries.length === 0 && orchestrated === false;
  if (entries.length === 0 && !running && !declined) return null;

  if (declined) {
    return (
      <div className="agent-transcript">
        <p className="agent-transcript__head">How it was worked out</p>
        <ol className="agent-transcript__list">
          <li className="agent-transcript__row agent-transcript__row--refuse">
            <span className="agent-transcript__who">{speaker("orchestrator")}</span>
            <span className="agent-transcript__text">
              {planNote(planReason ?? "")}
            </span>
            <span className="agent-transcript__tag">no plan</span>
          </li>
        </ol>
      </div>
    );
  }

  return (
    <div className="agent-transcript">
      <p className="agent-transcript__head">
        {running ? "Working on it…" : "How it was worked out"}
      </p>
      <ol className="agent-transcript__list">
        {entries.map((entry) => (
          <li
            key={entry.seq}
            className={cn(
              "agent-transcript__row",
              `agent-transcript__row--${entry.kind}`,
            )}
          >
            <span className="agent-transcript__who">
              {entry.kind === "ask"
                ? `${speaker(entry.frm)} → ${speaker(entry.to)}`
                : speaker(entry.frm)}
            </span>
            <span className="agent-transcript__text">{entry.text}</span>
            {/* A refusal is the point of having separate agents; it is not an
                error and must not be shown as one. */}
            {entry.kind === "refuse" ? (
              <span className="agent-transcript__tag">declined</span>
            ) : null}
            {entry.kind === "queue" ? (
              <span className="agent-transcript__tag">awaiting you</span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
