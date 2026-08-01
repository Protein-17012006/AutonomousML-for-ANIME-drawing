// Wire types mirror the FastAPI service SSE schema.

export type QA = "pass" | "abstain" | "flag";
export type PairAction = "needs_key" | "filled" | "generated";
export type PairRoute = "hold" | "rife" | "snap_preserve" | "generative";
export type RegionBox = [number, number, number, number];
export type InputMode = "frames" | "video";

export interface PairEvent {
  index: number;
  action: PairAction;
  qa?: QA | null;
  route?: PairRoute | null;
  keys_requested?: number;
  reason?: string;
  verdict_prob?: number | null; // likelihood of error
  uncertainty?: number | null; // level of uncertainty of verdict prob
  mid_url?: string | null;
  correction?: {
    status: string;
    keys_used: number;
    rounds: { action: string; reason: string }[];
  } | null;
}

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
  box?: RegionBox;
  annotated_url?: string;
}

//! REMOVE PLANTED PROPS
export interface ResultEvent {
  // sent explicitly by the server; absent only on sessions stored before it existed
  sid?: number | null;
  n_autopass: number;
  n_corrected: number;
  flagged: number[];
  abstained: number[];
  keys_requested_total: number;
  // compare = box-style side-by-side ORIGINAL|RECON loop (absent on older sessions
  // and when every gap was gate-refused)
  artifacts?: { montage: string; video: string; report?: string; compare?: string };
  explanations?: Record<string, Explanation>;
  pair_mids?: Record<string, string>;
  key_urls?: Record<string, string>;
  sampling?: {
    source_frames?: number;
    requested_stride?: number;
    stride?: number;
    kept?: number;
    cadence_fps?: number;
    smoothness?: number;
    output_fps?: number;
    duration?: number;
    interpolator?: "rife" | "gimm";
    planted?: string;
    planted_type?: string;
    planted_src?: string;
  } | null;
  csq?: CsqBand | null;
  qa_degraded?: boolean;
}

//! REMOVE (your change): obsolete frontend DemoResult removed with the comparison templates.
