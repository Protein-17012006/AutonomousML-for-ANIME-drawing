// Wire types — mirror the FastAPI service SSE schema (service/schemas.py).

export type QA = "pass" | "abstain" | "flag";

export interface PairEvent {
  index: number;
  action: string;            // "needs_key" | "filled" | "fill" | ...
  qa?: QA | null;
  route?: string | null;     // "hold" | "rife" | "snap_preserve" — cadence engine for a filled pair
  keys_requested?: number;
  reason?: string;
  verdict_prob?: number | null;   // P(error), calibrated — drives the confidence meter + abstain band
  uncertainty?: number | null;    // CSQ uncertainty u — selects the abstain-band threshold bin
  mid_url?: string | null;   // in-between PNG url, streamed live with each pair
}

// calibrated abstain band for the confidence dial: per-u-bin thresholds on p_error
export interface CsqBand {
  tau_pass: number[];
  tau_flag: number[];
  u_edges: number[];
  u_max: number;
}

export interface Explanation {
  err_type: string;
  region: string;
  explanation: string;
  box?: number[];   // fractional [x, y, w, h] (0..1) of the defect region, for the overlay
}

export interface ResultEvent {
  n_autopass: number;
  flagged: number[];
  abstained: number[];
  keys_requested_total: number;
  artifacts?: { montage: string; video: string };
  explanations?: Record<string, Explanation>;
  pair_mids?: Record<string, string>;   // pair index -> in-between PNG url (for the line-test)
  csq?: CsqBand | null;                 // calibrated abstain band for the dial (box engines only)
}

export interface DemoResult {
  video: string;          // side-by-side fallback
  video_orig?: string;    // ORIGINAL cut (src + hidden GT) — for the before/after wipe
  video_rife?: string;    // RECON cut (src + RIFE mids) — wiped against the original
  frames: number;
  src: number;
  gt: number;
}
