// Humanize machine tokens before they reach artist-facing copy.
// Sources: service/engines.py region/err_type enums + service/schemas.py csq reason string.
// A handful of lookup maps so the QA note reads like a sakkan's margin note, not an ML dump.

const REGION: Record<string, string> = {
  tl: "top-left", tc: "top-centre", tr: "top-right",
  ml: "mid-left", mc: "centre", mr: "mid-right",
  bl: "bottom-left", bc: "bottom-centre", br: "bottom-right",
  whole: "whole frame", none: "",
};

const ERR_TYPE: Record<string, string> = {
  ghost: "ghosting", blur: "blur/soft", flicker: "flicker/pop",
  morph: "warp/melt", identity_drift: "character drift",
  scene_break: "broken arc", none: "",
};

const ACTION: Record<string, string> = {
  needs_key: "needs a key", filled: "filled", fill: "filled",
};

// the 3-state QA verdict in artist language (not the raw machine token).
// pass = the co-pilot vouches; abstain = it won't vouch; flag = it thinks it's wrong.
const QA: Record<string, string> = {
  pass: "on-model", abstain: "unsure", flag: "off-model",
};

export const regionLabel = (r?: string): string => (r ? REGION[r] ?? r : "");
export const errTypeLabel = (e?: string): string => (e ? ERR_TYPE[e] ?? e : "");
export const actionLabel = (a?: string): string => (a ? ACTION[a] ?? a.replace(/_/g, " ") : "");
export const qaLabel = (q?: string | null): string => (q ? QA[q] ?? q : "");

// "csq:flag p=0.82 u=0.31" -> "Error likelihood 82% · uncertainty 31%"
// (the dial already shows "% clean"; the tooltip should explain that number in words,
//  not dump the wire string). Falls back to the raw reason if it doesn't parse.
export function readableReason(reason?: string | null): string {
  if (!reason) return "";
  const m = reason.match(/p=([\d.]+).*?u=([\d.]+)/);
  if (!m) return reason;
  const p = Math.round(parseFloat(m[1]) * 100);
  const u = Math.round(parseFloat(m[2]) * 100);
  return `Error likelihood ${p}% · uncertainty ${u}%`;
}
