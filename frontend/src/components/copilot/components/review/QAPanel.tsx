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
  statusGlyph,
} from "../../lib/pairView";
import {
  errTypeLabel,
  qaLabel,
  readableReason,
  regionLabel,
} from "../../labels";
import { cn } from "@/lib/utils";

export function QAPanel({
  p,
  band,
  ex,
}: {
  p: PairEvent | null;
  band?: CsqBand | null;
  ex?: Explanation;
}) {
  if (!p)
    return (
      <div className="qapanel qapanel-empty">
        Pick a pair (click, or J/K) to see the co-pilot&rsquo;s read.
      </div>
    );
  if (p.action === "needs_key") {
    return (
      <div className="qapanel qapanel-needskey">
        <div className="qap-head">
          <span className="sglyph sglyph-needs_key" aria-hidden="true">
            ✎
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
          {statusGlyph(p)}
        </span>
        pair {p.index} · {qaLabel(p.qa)}
      </div>
      <div className="qap-body">
        {hasDial ? (
          // one number on screen ("% clean") + the abstain band drawn to scale; the raw
          // error-likelihood / uncertainty (= the same fact restated) lives in the dial tooltip.
          <div className="qap-gauge" title={rigor}>
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
        ) : (
          <div className="qap-readout">
            <div className="qap-pct">
              <b>{qaLabel(p.qa)}</b>
            </div>
            <div className="qap-rigor">no calibrated score (demo engine)</div>
          </div>
        )}
      </div>
      {ex && (
        <div className="qap-explain">
          ✎ {errTypeLabel(ex.err_type)}
          {regionLabel(ex.region) ? `, ${regionLabel(ex.region)}` : ""} —{" "}
          {ex.explanation}
        </div>
      )}
    </div>
  );
}
