# benchmark/smallgap/build_suite.py
"""LOCAL suite builder: scan decoded native frames, cut 17-frame windows,
classify each window's regime, calibrate thresholds, emit a window plan.

Operational: reads decoded PNG frame dirs (one dir per contiguous segment),
no model calls. Calibration prints the step-motion distribution so the user
picks tau_hold / tau_snap; defaults are percentile-based and overridable.

Decode the frames first with .scratch/smallgap/extract_frames.py (cv2), which
replaces the plan's ffmpeg shell step because no system ffmpeg is on PATH.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

from benchmark.lib.signals.motion_primitives import load_frames
from benchmark.smallgap.prep.decimate import decimate
from benchmark.smallgap.interp.regime import step_motions, scene_cut, classify

WINDOW_LEN = 17


def _frame_paths(d: str) -> list[str]:
    return [os.path.join(d, n) for n in sorted(os.listdir(d))
            if n.lower().endswith((".png", ".jpg"))]


def scan_windows(frame_dir: str, stride: int = WINDOW_LEN) -> list[dict]:
    """Cut non-overlapping 17-frame windows from one CONTIGUOUS segment dir;
    compute per-source-step motion + a scene-cut flag for each window."""
    paths = _frame_paths(frame_dir)
    w = decimate(WINDOW_LEN)
    out = []
    for start in range(0, len(paths) - WINDOW_LEN + 1, stride):
        win = paths[start:start + WINDOW_LEN]
        src = load_frames([win[i] for i in w.source])
        ms = step_motions(src)
        has_cut = any(scene_cut(src[i], src[i + 1]) for i in range(len(src) - 1))
        out.append({"src_dir": frame_dir, "frame0": win[0],
                    "win_start": start, "step_motions": ms, "has_cut": has_cut})
    return out


def calibrate(all_ms: list[float]) -> tuple[float, float]:
    """Percentile-based starting thresholds; refine by full-res spot-check."""
    arr = np.array(all_ms)
    return float(np.percentile(arr, 10)), float(np.percentile(arr, 90))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-root", required=True)   # .scratch/smallgap/frames
    ap.add_argument("--out", default="benchmark/suites/suite_smallgap/window_plan.json")
    ap.add_argument("--tau-hold", type=float, default=None)
    ap.add_argument("--tau-snap", type=float, default=None)
    ap.add_argument("--stride", type=int, default=WINDOW_LEN)
    args = ap.parse_args()

    windows = []
    for series in sorted(os.listdir(args.frames_root)):
        sdir = os.path.join(args.frames_root, series)
        if not os.path.isdir(sdir):
            continue
        for vid in sorted(os.listdir(sdir)):
            vdir = os.path.join(sdir, vid)
            if os.path.isdir(vdir):
                for win in scan_windows(vdir, args.stride):
                    win["series"] = series
                    windows.append(win)

    if not windows:
        print("no windows found — decode frames first"); return 1

    all_ms = [m for win in windows for m in win["step_motions"]]
    tau_hold = args.tau_hold if args.tau_hold is not None else calibrate(all_ms)[0]
    tau_snap = args.tau_snap if args.tau_snap is not None else calibrate(all_ms)[1]
    print(f"step-motion distribution (n={len(all_ms)} steps): "
          f"p05={np.percentile(all_ms,5):.4f} p10={np.percentile(all_ms,10):.4f} "
          f"p50={np.percentile(all_ms,50):.4f} p90={np.percentile(all_ms,90):.4f} "
          f"p95={np.percentile(all_ms,95):.4f} max={max(all_ms):.4f}")
    print(f"using tau_hold={tau_hold:.4f}  tau_snap={tau_snap:.4f}")

    for i, win in enumerate(windows):
        win["wid"] = f"w{i:04d}"
        win["regime"] = classify(win["step_motions"], tau_hold=tau_hold,
                                 tau_snap=tau_snap, has_cut=win["has_cut"])
    counts = {r: sum(w["regime"] == r for w in windows)
              for r in ("hold", "small", "snap")}
    print(f"regime counts (n_windows={len(windows)}): {counts}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"tau_hold": tau_hold, "tau_snap": tau_snap,
                   "window_len": WINDOW_LEN, "windows": windows}, f, indent=2)
    print(f"wrote {args.out} ({len(windows)} windows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
