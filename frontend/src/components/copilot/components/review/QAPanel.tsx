// focused-pair QA panel: the calibrated verdict made the centerpiece (the moat).
// Always shows the FOCUSED pair's read large — a big 180° dial + the calibrated abstain band drawn to
// scale + p_error/uncertainty in plain words + the in-between thumbnail with its akaire region. The
// defensible thing (calibrated 3-state QA) gets an owned surface, not just a 44px inline crumb.
// Extracted from CopilotApp.tsx.
import type { CsqBand, Explanation, PairEvent } from "../../types";
import { statusClass } from "../../lib/pairView";
import { actionLabel, errTypeLabel, regionLabel } from "../../labels";
import { cn } from "@/lib/utils";
import { Pencil } from "lucide-react";
import { ConfidenceMeter } from "./ConfidenceMeter";
import { StatusGlyph } from "./StatusGlyph";

export function QAPanel({
  p,
  band,
  ex,
}: {
  p: PairEvent | null;
  band?: CsqBand | null;
  ex?: Explanation;
}) {
  const tone =
    p?.qa === "pass" ? "pass" : p?.qa === "abstain" ? "abstain" : "flag";

  return (
    <>
      {!p ? (
        <div className="qapanel qapanel-empty">
          <div className="qap-head">
            
          </div>
          <p className="qap-why">QA status is empty for this view.</p>
        </div>
      ) : (
        <div className={cn("qapanel", `qapanel-${tone}`)}>
          <div className="qap-head">
            <span
              className={cn("sglyph", `sglyph-${statusClass(p)}`)}
              aria-hidden="true"
            >
              <StatusGlyph pair={p} />
            </span>
            pair {p.index} · {actionLabel(p.action)}
          </div>

          {p.action !== "needs_key" && (
            <div className="qap-body">
              <ConfidenceMeter p={p} band={band} />
            </div>
          )}

          {ex && (
            <div className="log-explain">
              <Pencil className="mr-1 inline size-3" aria-hidden="true" />
              {errTypeLabel(ex.err_type)}
              {regionLabel(ex.region) ? `, ${regionLabel(ex.region)}` : ""}{" "}
              — {ex.explanation}
            </div>
          )}
        </div>
      )}
    </>
  );
}
