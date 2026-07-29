// focused-pair QA panel: the calibrated verdict made the centerpiece (the moat).
// Always shows the FOCUSED pair's read large — a big 180° dial + the calibrated abstain band drawn to
// scale + p_error/uncertainty in plain words + the in-between thumbnail with its akaire region. The
// defensible thing (calibrated 3-state QA) gets an owned surface, not just a 44px inline crumb.
// Extracted from CopilotApp.tsx.
import type { CsqBand, Explanation, PairEvent } from "../../types";
import {
  ARC,
  abstainZone,
  clamp01,
  statusClass,
} from "../../lib/pairView";
import {
  errTypeLabel,
  qaLabel,
  readableReason,
  regionLabel,
} from "../../labels";
import { cn } from "@/lib/utils";
import { KeyRound, Pencil } from "lucide-react";
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
  //! REMOVE: REDUNDANT SINCE FIRST PAIR IS PICKED IF THERE IS ANY
  if (!p)
    return (
      <div className="qapanel qapanel-empty">
        Pick a pair (click, or J/K) to see the co-pilot&rsquo;s read.
      </div>
    );
//! REMOVE: REDUNDANT, INFO ALREADY IN PANEL
  if (p.action === "needs_key") {
    return (
      <div className="qapanel qapanel-needskey">
        <div className="qap-head">
          <span className="sglyph sglyph-needs_key" aria-hidden="true">
            <KeyRound className="size-3" strokeWidth={2.5} aria-hidden="true" />
          </span>
          pair {p.index} · needs a key
        </div>
        <p className="qap-why">
          Gap too large to fill reliably — draw a breakdown key here.
        </p>
      </div>
    );
  }

  const tone =
    p.qa === "pass" ? "pass" : p.qa === "abstain" ? "abstain" : "flag";
  const hasDial = p.verdict_prob != null;
  const clean = clamp01(1 - (p.verdict_prob ?? 0));
  const zone = abstainZone(p, band);
  const rigor = readableReason(p.reason);
  return (
    <div className={cn("qapanel", `qapanel-${tone}`)}>

      <div className="qap-head">
        <span className={cn("sglyph", `sglyph-${statusClass(p)}`)} aria-hidden="true">
          <StatusGlyph pair={p} />
        </span>
        pair {p.index} · {qaLabel(p.qa)}
      </div>

      <div className="qap-body">
        {hasDial ? (
          <div className="qap-gauge" title={rigor}>
            {/* //! REVIEW: DISPLAY DIAL USING PRE-BUILT COMPONENT */}
            <svg className="qap-dial" viewBox="0 0 44 26" aria-hidden="true">
              <path className="cg-track" d={ARC} pathLength={1} />
              {zone === "forced" ? (
                <path
                  className="cg-abstain"
                  d={ARC}
                  pathLength={1}
                  style={{ strokeDasharray: "1 0" }}
                />
              ) : zone ? (
                <path
                  className="cg-abstain"
                  d={ARC}
                  pathLength={1}
                  style={{
                    strokeDasharray: `0 ${zone.from} ${zone.to - zone.from} ${1 - zone.to}`,
                  }}
                />
              ) : null}
              <path
                className="cg-fill"
                d={ARC}
                pathLength={1}
                style={{ strokeDashoffset: 1 - clean }}
              />
            </svg>
            {/* //! REVIEW: UNSURE P VERDICT AND ABSTAIN ZONE */}
            <div className="qap-readout">
              <div className="qap-pct">
                <b>{Math.round(clean * 100)}%</b> clean
              </div>
              {zone === "forced" ? (
                <div className="qap-zone">unsure zone</div>
              ) : zone ? (
                <div className="qap-zone">
                  abstain {Math.round(zone.from * 100)}–
                  {Math.round(zone.to * 100)}%
                </div>
              ) : null}
            </div>
          </div>
        ) :  (
          //! REMOVE: EVERY PAIR HAS P VERDICT, NO NEED HASDIAL STATE
          <div className="qap-readout">
            <div className="qap-pct">
              <b>{qaLabel(p.qa)}</b>
            </div>
            <div className="qap-rigor">no calibrated score (demo engine)</div>
          </div>
        )}
      </div>
      {/* //! REVIEW: TOO MUCH DETAIL IN THIS COMPONENT */}
      {ex && (
        <div className="qap-explain">
          <Pencil className="mr-1 inline size-3" aria-hidden="true" />
          {errTypeLabel(ex.err_type)}
          {regionLabel(ex.region) ? `, ${regionLabel(ex.region)}` : ""} —{" "}
          {ex.explanation}
        </div>
      )}
    </div>
  );
}
