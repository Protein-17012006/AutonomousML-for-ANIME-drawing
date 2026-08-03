"use client";

// What the agent PROPOSED, and the button that is the only way it happens.
//
// The rule this card exists to make visible: the agent never runs anything. It
// suggests one thing per turn and stops. Two proposals — re-running the cut and
// remembering a preference — are confirm-gated on the server as well, and it
// re-checks on the way in, so hiding the distinction here would only mislead
// the artist about what they are agreeing to.

import { Check, CircleAlert, Play, ShieldQuestion } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AgentAction } from "../../api";

/** Plain descriptions of what accepting actually does, in the artist's terms. */
function describe(action: AgentAction): string {
  const args = action.args;
  switch (action.tool) {
    case "explain_pair":
      return `Show the evidence behind pair ${args.index}.`;
    case "show_annotated":
      return `Open the marked-up drawing for pair ${args.index}.`;
    case "open_board":
      return `Open the review board at pair ${args.index}.`;
    case "export_bundle":
      return "Download the report, montage and reconstructed cut.";
    case "rerun_session": {
      const parts = [
        args.cadence != null ? `cadence ${args.cadence}` : null,
        args.smoothness != null ? `smoothness x${args.smoothness}` : null,
        args.interpolator ? `${String(args.interpolator)} engine` : null,
      ].filter(Boolean);
      return `Re-draw every in-between at ${parts.join(", ")}. This replaces the frames you have now.`;
    }
    case "remember_memory":
      return `Remember for future sessions — ${String(args.key)}: ${String(args.value)}.`;
    case "image_edit":
      return `Open pair ${args.index} so you can paint over the region that is wrong. You choose the region — the co-pilot never picks it for you.`;
    default:
      return action.label;
  }
}

interface Props {
  action?: AgentAction | null;
  done?: boolean;
  note?: string | null;
  rejectedTool?: string;
  busy?: boolean;
  onAccept: () => void;
  onDismiss: () => void;
}

export function AgentActionBubble({
  action,
  done,
  note,
  rejectedTool,
  busy,
  onAccept,
  onDismiss,
}: Props) {
  // The server refused the tool the model named. Say so: the reply above may
  // still describe it, and a described action with no button reads as broken.
  if (!action && rejectedTool) {
    return (
      <p className="agent-action agent-action--refused">
        <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          It suggested <code>{rejectedTool}</code>, but the server would not
          accept it — so nothing was proposed. Try asking a different way.
        </span>
      </p>
    );
  }

  if (!action) return null;

  if (done) {
    return (
      <p className="agent-action agent-action--done">
        <Check className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>{note ?? `${action.label} — done.`}</span>
      </p>
    );
  }

  return (
    <div className="agent-action">
      <div className="agent-action__body">
        <p className="agent-action__label">
          {action.needs_confirm ? (
            <ShieldQuestion className="size-4 shrink-0" aria-hidden />
          ) : (
            <Play className="size-4 shrink-0" aria-hidden />
          )}
          {action.label}
        </p>
        <p className="agent-action__detail">{describe(action)}</p>
        {note ? <p className="agent-action__note">{note}</p> : null}
      </div>
      <div className="agent-action__buttons">
        <Button size="sm" variant="ghost" onClick={onDismiss} disabled={busy}>
          Not now
        </Button>
        <Button size="sm" onClick={onAccept} disabled={busy}>
          {action.needs_confirm ? "Confirm" : "Do it"}
        </Button>
      </div>
    </div>
  );
}
