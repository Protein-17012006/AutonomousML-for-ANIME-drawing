const REGION: Record<string, string> = {
  tl: "top-left",
  tc: "top-centre",
  tr: "top-right",
  ml: "mid-left",
  mc: "centre",
  mr: "mid-right",
  bl: "bottom-left",
  bc: "bottom-centre",
  br: "bottom-right",
  whole: "whole frame",
  none: "",
};

const ERR_TYPE: Record<string, string> = {
  ghost: "ghosting",
  blur: "softness/blur",
  flicker: "flicker",
  morph: "shape warp",
  identity_drift: "character drift",
  scene_break: "scene break",
  none: "",
};

//! REVIEW: CONFLICT WITH PAIR-ACTION INTERFACE
const ACTION: Record<string, string> = {
  needs_key: "needs a key",
  filled: "filled",
  fill: "filled",
};

const QA: Record<string, string> = {
  pass: "On-model",
  abstain: "Unsure",
  flag: "Off-model",
};

// GET REGION
export const regionLabel = (r?: string): string => (r ? (REGION[r] ?? r) : "");

// GET ERROR TYPE
export const errTypeLabel = (e?: string): string =>
  e ? (ERR_TYPE[e] ?? e.replace(/_/g, " ")) : ""; // replace all matching "_" with " "

// GET ACTION LABEL
export const actionLabel = (a?: string): string =>
  a ? (ACTION[a] ?? a.replace(/_/g, " ")) : "";

// GET QA LABEL
export const qaLabel = (q?: string | null): string => (q ? (QA[q] ?? q) : "");

// GET LIKELIHOOD OF ERROR + UNCERTAINTY FROM PAIR'S REASON PROP
export function readableReason(reason?: string | null): string {
  if (!reason) return "";
  const m = reason.match(/p=([\d.]+).*?u=([\d.]+)/);
  if (!m) return reason;
  const p = Math.round(parseFloat(m[1]) * 100);
  const u = Math.round(parseFloat(m[2]) * 100);
  return `Error likelihood ${p}% · uncertainty ${u}%`;
}
