// confidence meter — "% clean" = 1 − P(error) read on a calibrated 180° dial (a measurement,
// not a download). The indicator arc draws itself like the run-loader stroke (pathLength=1 →
// dashoffset = 1 − clean). Raw csq p/u stay in the tooltip (rigor on hover).
// Extracted from CopilotApp.tsx.
import type { CsqBand, PairEvent } from "../../types";
import { ARC, abstainZone, clamp01 } from "../../lib/pairView";
import { readableReason } from "../../labels";
import { cn } from "@/lib/utils";

export function ConfidenceMeter({
  p,
  band,
}: {
  p: PairEvent;
  band?: CsqBand | null;
}) {
  if (p.verdict_prob == null || p.action === "needs_key") return null;
  const clean = clamp01(1 - p.verdict_prob);
  const pct = Math.round(clean * 100);
  const tone =
    p.qa === "pass" ? "pass" : p.qa === "abstain" ? "abstain" : "flag";
  const zone = abstainZone(p, band);
  return (
    <div
      className={cn("confgauge", `confgauge-${tone}`)}
      title={readableReason(p.reason)}
    >
      <svg className="confgauge-dial" viewBox="0 0 44 26" aria-hidden="true">
        <path className="cg-track" d={ARC} pathLength={1} />
        {zone === "forced" ? (
          <path
            className="cg-abstain"
            d={ARC}
            pathLength={1}
            style={{ strokeDasharray: "1 0" }}
          />
        ) : zone ? (
          // draw ONLY the [from,to] segment: 0-dash, gap to `from`, visible dash, gap to end
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
      <span className="confgauge-label">
        <b>{pct}%</b> clean
        {zone === "forced" ? (
          <i className="cg-zone"> · unsure zone</i>
        ) : zone ? (
          <i className="cg-zone">
            {" "}
            · abstain {Math.round(zone.from * 100)}–{Math.round(zone.to * 100)}%
          </i>
        ) : null}
      </span>
    </div>
  );
}
