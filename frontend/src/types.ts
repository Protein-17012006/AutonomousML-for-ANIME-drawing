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
  // correction-loop trace (director decisions) — mirrors PairEvent.correction in schemas.py
  correction?: {
    status: string;
    keys_used: number;
    rounds: { action: string; reason: string }[];
  } | null;
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
  n_corrected: number;
  flagged: number[];
  abstained: number[];
  keys_requested_total: number;
  artifacts?: { montage: string; video: string; report?: string };
  explanations?: Record<string, Explanation>;
  pair_mids?: Record<string, string>;   // pair index -> in-between PNG url (for the line-test)
  key_urls?: Record<string, string>;    // key index -> key PNG url (drop-a-video flow: keys are server-side)
  sampling?: {                          // drop-a-video decimation summary (null for PNG upload)
    source_frames: number;
    requested_stride: number;
    stride: number;                     // > requested_stride when the clip was auto-fit (coarser)
    kept: number;
  } | null;
  csq?: CsqBand | null;                 // calibrated abstain band for the dial (box engines only)
  qa_degraded?: boolean;                // true when the served VLM was unreachable during the run
}

export interface DemoResult {
  video: string;          // side-by-side fallback
  video_orig?: string;    // ORIGINAL cut (src + hidden GT) — for the before/after wipe
  video_rife?: string;    // RECON cut (src + RIFE mids) — wiped against the original
  frames: number;
  src: number;
  gt: number;
}
