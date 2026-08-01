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
};

function speaker(name: string): string {
  return SPEAKER[name] ?? name;
}

export function AgentTranscript({
  entries,
  running,
}: {
  entries: TranscriptEntry[];
  running: boolean;
}) {
  if (entries.length === 0 && !running) return null;

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
