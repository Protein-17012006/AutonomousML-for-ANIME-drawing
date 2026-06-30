"""Deterministic contamination pre-filter — ADR-0012 §2 (run BEFORE labeling).

AUTO-FLAGS the contamination a VLM would learn as a feature and that is RELIABLY separable from a
legitimate character frame: **burned-in subtitles** (bright text strokes) and **letterbox** bars.
Generated-data twist: the generator REPRODUCES burned-in subtitles (trained on subbed anime), so
this is intrinsic, not avoidable by clean generation.

Validation finding (2026-06-17, suite_identity kept-vs-dropped): **dark-plate and VFX-storm are NOT
deterministically separable** with simple global features — a dark *character* close-up looks like
a dark plate, and a downsampled particle storm doesn't score high-gradient. Those are really
"no usable subject" rejections, a different problem; this filter REPORTS them as ADVISORY only and
leaves the call to the labeling stage (Claude-eyes). So: subtitle/letterbox = auto-flag;
dark/vfx = advisory.

PIL + numpy only (no GPU, no cv2). A CHEAP pre-screen whose positives a human/Claude confirms, not
a final judge. Per ADR-0012, it LOGS what it flags — never silently drops.

    python -m benchmark.lib.labeling.contamination_filter --clips <dir-of-clip-subdirs> --out contam.json
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
from PIL import Image, ImageFilter

_FRAME_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# Calibrated on suite_identity kept(42) vs dropped(13), 2026-06-17.
# AUTO-FLAG only the two contaminants that are RELIABLY separable from a legitimate character
# frame and that a VLM would learn as a feature: subtitles and letterbox. (Validation: stroke-based
# subtitle put the one clear-subtitle clip at 0.49 vs suite max 0.028 — clean separation, 0 suite
# false-positives.)
T_LETTERBOX = 0.085     # >8.5% of height in top+bottom near-black uniform bars
T_SUBTITLE = 0.10       # densest bottom-band row is >10% persistent bright text-strokes
# ADVISORY ONLY (reported, never auto-flag): dark-plate and vfx-storm are NOT deterministically
# separable from a legitimately-dark or effect-heavy CHARACTER scene with these global features
# (dark drops 37-51 overlap dark character scenes 40-57; downsampled particle storms don't score
# high-gradient). "No usable subject" is a labeling-stage / Claude-eyes call, not this pre-filter.
T_DARK_ADV = 45.0       # advisory: median frame mean-luma below this = possibly a dark plate
T_VFX_ADV = 0.08        # advisory: high-gradient fraction (weak signal at low res)


def _frames(clip_dir: str) -> list[str]:
    return [os.path.join(clip_dir, n) for n in sorted(os.listdir(clip_dir))
            if n.lower().endswith(_FRAME_EXTS)]


def _gray(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)


def _letterbox_frac(g: np.ndarray) -> float:
    """Fraction of height taken by near-black, low-variance full-width bars top+bottom."""
    H = g.shape[0]
    dark_row = (g.mean(axis=1) < 18) & (g.std(axis=1) < 12)
    top = 0
    for r in range(H):
        if dark_row[r]:
            top += 1
        else:
            break
    bot = 0
    for r in range(H - 1, -1, -1):
        if dark_row[r]:
            bot += 1
        else:
            break
    return (top + bot) / H


def _vfx_frac(g: np.ndarray) -> float:
    """Fraction of pixels with strong local gradient — high everywhere = chaotic VFX."""
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    grad = gx + gy
    return float((grad > 45).mean())


def _text_strokes(path: str) -> np.ndarray:
    """Bool mask of bright THIN strokes with a dark neighbour — subtitle text, not bright
    background. A solid bright region's interior pixels have bright neighbours (erosion stays
    high) and are excluded; only bright pixels adjacent to dark (stroke edges / outlined text)
    survive."""
    img = Image.open(path).convert("L")
    g = np.asarray(img, np.float32)
    mn = np.asarray(img.filter(ImageFilter.MinFilter(3)), np.float32)   # local erosion
    return (g > 225) & (mn < 130)


def score_clip(clip_dir: str) -> dict:
    paths = _frames(clip_dir)
    if not paths:
        return {"n": 0, "contaminated": False, "reasons": ["no frames"]}
    grays = [_gray(p) for p in paths]
    H, W = grays[0].shape

    letterbox = float(np.median([_letterbox_frac(g) for g in grays]))
    dark = float(np.median([g.mean() for g in grays]))
    vfx = float(np.median([_vfx_frac(g) for g in grays]))

    # subtitle: bright text STROKES persistent in the same bottom-band location across frames.
    b0, b1 = int(0.72 * H), int(0.98 * H)
    strokes = np.stack([_text_strokes(p)[b0:b1, :] for p in paths], axis=0)  # [n, bh, W]
    persistent = strokes.mean(axis=0) > 0.4              # stroke at this pixel in >40% of frames
    row_density = persistent.mean(axis=1)               # per-row fraction of persistent strokes
    band_score = float(row_density.max()) if row_density.size else 0.0
    spread = float(persistent.any(axis=0).mean())       # horizontal extent of the text line
    subtitle = band_score if spread > 0.2 else 0.0

    reasons = []           # auto-flag: reliably-separable feature contamination only
    if letterbox > T_LETTERBOX:
        reasons.append(f"letterbox({letterbox:.2f})")
    if subtitle > T_SUBTITLE:
        reasons.append(f"subtitle({subtitle:.3f})")
    advisory = []          # reported, NOT a drop: needs labeling-stage / Claude-eyes confirmation
    if dark < T_DARK_ADV:
        advisory.append(f"dark({dark:.0f})")
    if vfx > T_VFX_ADV:
        advisory.append(f"vfx({vfx:.2f})")
    return {"n": len(paths), "letterbox": round(letterbox, 3),
            "subtitle": round(subtitle, 4), "dark": round(dark, 1),
            "vfx": round(vfx, 3), "contaminated": bool(reasons),
            "reasons": reasons, "advisory": advisory}


def run(clips_dir: str, out: str | None) -> int:
    subs = sorted(d for d in os.listdir(clips_dir)
                  if os.path.isdir(os.path.join(clips_dir, d)))
    rows, flagged, advised = [], 0, 0
    for d in subs:
        r = score_clip(os.path.join(clips_dir, d))
        r["clip"] = d
        rows.append(r)
        if r["contaminated"]:
            flagged += 1
            print(f"  FLAG {d}: {', '.join(r['reasons'])}")
        elif r.get("advisory"):
            advised += 1
            print(f"  review {d}: {', '.join(r['advisory'])}  (advisory — confirm at labeling)")
    print(f"\n{flagged}/{len(rows)} auto-flagged contaminated (subtitle/letterbox); "
          f"{advised} advisory (dark/vfx — labeling-stage call). Logged, not silently dropped.")
    if out:
        json.dump({"clips_dir": clips_dir, "thresholds":
                   {"letterbox": T_LETTERBOX, "subtitle": T_SUBTITLE,
                    "dark": T_DARK_ADV, "vfx": T_VFX_ADV}, "clips": rows},
                  open(out, "w"), indent=1)
        print(f"wrote {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clips", required=True, help="dir of clip subdirs (frame_*.png)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    return run(args.clips, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
