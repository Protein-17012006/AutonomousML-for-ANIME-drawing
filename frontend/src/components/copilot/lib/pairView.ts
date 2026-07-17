// Presentation helpers for a PairEvent — the decision-log copy + confidence-dial maths.
// Pure functions/constants shared by ConfidenceMeter, QAPanel, FrameCard, ReviewWorkbench.
// Extracted from CopilotApp.tsx.
import type { CsqBand, PairEvent } from "../types";

/* ---------- decision-log copy helpers ---------- */
export function whyText(p: PairEvent): string {
  if (p.action === "needs_key")
    return `Gap too large — draw ${p.keys_requested ?? 1} breakdown key${(p.keys_requested ?? 1) > 1 ? "s" : ""} here`;
  if (p.qa === "pass") return "On-model — the co-pilot is confident";
  if (p.qa === "abstain") return "Unsure — worth a second look";
  if (p.qa === "flag") return "Likely off-model — review / redraw";
  return "";
}

export function statusClass(p: PairEvent): string {
  return p.action === "needs_key" ? "needs_key" : p.qa ?? "";
}

/* a shape per status so the state survives without colour (deuteranopia-safe; structure = info) */
export function statusGlyph(p: PairEvent): string {
  if (p.action === "needs_key") return "✎";
  if (p.qa === "pass") return "✓";
  if (p.qa === "abstain") return "~";
  if (p.qa === "flag") return "!";
  return "·";
}

/* confidence meter — "% clean" = 1 − P(error) read on a calibrated 180° dial (a measurement,
   not a download). The indicator arc draws itself like the run-loader stroke (pathLength=1 →
   dashoffset = 1 − clean). Raw csq p/u stay in the tooltip (rigor on hover). */
export const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

/** Resolve the abstain zone (on the dial's "clean" = 1 − p_error axis) for this pair's
 *  uncertainty bin. "forced" = the hard u_max gate makes it always-abstain. */
export function abstainZone(p: PairEvent, band?: CsqBand | null): { from: number; to: number } | "forced" | null {
  if (!band) return null;
  if (
    band.u_edges.length < 2 ||
    band.tau_pass.length !== band.u_edges.length - 1 ||
    band.tau_flag.length !== band.u_edges.length - 1
  ) return null;
  const u = p.uncertainty ?? 0;
  if (u > band.u_max) return "forced";
  const e = band.u_edges;
  let j = e.length - 2;
  for (let k = 0; k < e.length - 1; k++) { if (u <= e[k + 1]) { j = k; break; } }
  const tp = band.tau_pass[j], tf = band.tau_flag[j];
  if (tf <= tp) return null;                              // degenerate bin → nothing drawable
  return { from: clamp01(1 - tf), to: clamp01(1 - tp) };  // p_error→clean flips the ends
}

/* arc path shared by the inline dial + the focused-pair QA panel (a 180° gauge) */
export const ARC = "M4 24 A 18 18 0 0 1 40 24";
