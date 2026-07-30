import type { CsqBand, PairEvent } from "../types";

// GET PAIR ACTION STATUS
export function statusClass(p: PairEvent): string {
  return p.action === "needs_key" ? "needs_key" : (p.qa ?? "");
}

// FORCE RECEIVING NUMBER BETWEEN 0 & 1
export const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

// CALCULATE PASS, ABSTAIN, FLAG ZONES BASED ON CSQ BAND (USING UNCERTAINTY)
export function abstainZone(
  p: PairEvent,
  band?: CsqBand | null,
): { from: number; to: number } | "forced" | null {

  if (!band) return null;

  if (
    band.u_edges.length < 2 ||
    band.tau_pass.length !== band.u_edges.length - 1 ||
    band.tau_flag.length !== band.u_edges.length - 1
  )
    return null;

  const u = p.uncertainty ?? 0;

  if (u > band.u_max) return "forced";

  const e = band.u_edges;
  let j = e.length - 2;
  for (let k = 0; k < e.length - 1; k++) {
    if (u <= e[k + 1]) {
      j = k;
      break;
    }
  }
  const tp = band.tau_pass[j]
  const tf = band.tau_flag[j];
  if (tf <= tp) return null; 
  return { from: clamp01(1 - tf), to: clamp01(1 - tp) }; 
}

// SVG PATH
export const ARC = "M4 24 A 18 18 0 0 1 40 24";
