import {
  CircleHelp,
  Minus,
  Pencil,
  TriangleAlert,
  Check,
} from "lucide-react";
import type { PairEvent } from "../../types";

/** Semantic status mark shared by the chat-adjacent review surfaces. */
export function StatusGlyph({ pair }: { pair: PairEvent }) {
  const Icon =
    pair.action === "needs_key"
      ? Pencil
      : pair.qa === "pass"
        ? Check
        : pair.qa === "abstain"
          ? CircleHelp
          : pair.qa === "flag"
            ? TriangleAlert
            : Minus;

  return <Icon className="size-3" strokeWidth={2.5} aria-hidden="true" />;
}
