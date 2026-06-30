"""Artifact builders for the in-between co-pilot service.

Three outputs, ported from .scratch/copilot/demo_copilot.py:
  build_report  -> report.md    (text summary via reporting.report.summarize)
  build_montage -> montage.png  (one row per pair; green/yellow/red tinting)
  build_video   -> reconstructed.mp4  (filled frames concatenated via cv2.VideoWriter)
"""
from __future__ import annotations

import os
from typing import List

import numpy as np
from PIL import Image, ImageDraw

from inbetween_copilot.pipeline.copilot import CopilotResult
from inbetween_copilot.reporting.report import summarize


# colour map ported from demo_copilot.py
_STATUS_COLOR = {
    "pass":      (60, 200, 60),
    "abstain":   (230, 170, 40),
    "flag":      (230, 170, 40),
    "needs_key": (220, 60, 60),
}
_DEFAULT_COLOR = (90, 90, 90)


def _tint_color(pair) -> tuple:
    """Return the banner RGB for a pair (green/yellow/red)."""
    if pair.action == "needs_key":
        return _STATUS_COLOR["needs_key"]
    if pair.qa is None:
        return _DEFAULT_COLOR
    return _STATUS_COLOR.get(pair.qa.status, _DEFAULT_COLOR)


def build_report(result: CopilotResult, out_dir: str) -> str:
    """Write report.md to *out_dir* and return the path."""
    keys_drawn = len(result.pairs) + 1   # n pairs -> n+1 keys
    rep = summarize(result, keys_drawn)

    n_fill = sum(1 for p in result.pairs if p.action == "filled")
    n_gen  = sum(1 for p in result.pairs if p.action == "generated")
    n_need = sum(1 for p in result.pairs if p.action == "needs_key")

    lines = [
        "# In-Between Co-pilot — session report\n",
        f"**{rep.summary}**\n",
        f"- artist keys: {keys_drawn}  |  pairs: {len(result.pairs)}\n",
        f"- filled (interpolated): {n_fill}  |  generated: {n_gen}"
        f"  |  needs-key (gate refused): {n_need}\n",
        f"- auto-pass: {rep.auto_pass_rate:.0%}"
        f"  |  flagged for review: {rep.n_flagged}\n",
        "\n",
        "| pair | action | route | QA | reason |\n",
        "|---|---|---|---|---|\n",
    ]
    for p in result.pairs:
        qa_s  = p.qa.status if p.qa else "-"
        qa_r  = p.qa.reason if p.qa else "-"
        lines.append(
            f"| {p.index} | {p.action} | {p.route or '-'} | {qa_s} | {qa_r} |\n"
        )

    path = os.path.join(out_dir, "report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    return path


def build_montage(result: CopilotResult, keys: List[np.ndarray], out_dir: str,
                  regions: "dict[int, tuple] | None" = None) -> str:
    """Build a PNG montage (one row per pair: key_A | mid | key_B + coloured banner).

    Tinting follows demo_copilot.py:
      green  -> QA pass
      yellow -> QA abstain / flag
      red    -> action == needs_key

    regions: optional mapping of pair index -> (x0,y0,x1,y1) box on the mid cell.
             A 3px red rectangle is drawn on top of the mid frame for each listed pair.
    """
    if not result.pairs:
        # degenerate: blank 1×1
        path = os.path.join(out_dir, "montage.png")
        Image.new("RGB", (1, 1)).save(path)
        return path

    # infer cell size from the first key that exists
    sample = keys[0]
    H, W = sample.shape[:2]
    BANNER = 22
    cell_h = H + BANNER

    canvas = Image.new("RGB", (W * 3, cell_h * len(result.pairs)), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)

    for r, p in enumerate(result.pairs):
        y = r * cell_h
        color = _tint_color(p)
        draw.rectangle([0, y, W * 3 - 1, y + BANNER - 1], fill=color)
        label = (
            f"pair {p.index}: {p.action}/{p.route or '-'}"
            f"  QA={p.qa.status if p.qa else 'n/a'}"
        )
        draw.text((4, y + 4), label, fill=(0, 0, 0))

        # key_A
        key_a = keys[p.index] if p.index < len(keys) else np.zeros((H, W, 3), np.uint8)
        canvas.paste(Image.fromarray(key_a.astype(np.uint8)), (0, y + BANNER))

        # mid frame (centre of the pair's frames, or red placeholder if needs_key)
        if p.action in ("filled", "generated") and p.frames:
            mid_idx = len(p.frames) // 2
            mid = p.frames[mid_idx]
            if not isinstance(mid, np.ndarray):
                mid = np.array(mid, dtype=np.uint8)
            else:
                mid = mid.astype(np.uint8)
        else:
            mid = np.zeros((H, W, 3), np.uint8)
            mid[:, :, 0] = 90  # red-ish placeholder
        canvas.paste(Image.fromarray(mid), (W, y + BANNER))

        # draw region highlight on mid cell if provided
        if regions and p.index in regions and regions[p.index] is not None:
            rx0, ry0, rx1, ry1 = regions[p.index]
            # translate into canvas coordinates: mid cell starts at (W, y+BANNER)
            draw.rectangle(
                [W + rx0, y + BANNER + ry0, W + rx1, y + BANNER + ry1],
                outline=(255, 40, 40),
                width=3,
            )

        # key_B
        b_idx = p.index + 1
        key_b = keys[b_idx] if b_idx < len(keys) else np.zeros((H, W, 3), np.uint8)
        canvas.paste(Image.fromarray(key_b.astype(np.uint8)), (2 * W, y + BANNER))

    path = os.path.join(out_dir, "montage.png")
    canvas.save(path)
    return path


def _assemble_frames(result: CopilotResult) -> List[np.ndarray]:
    """Concatenate the filled/generated pairs into one ordered frame sequence.

    Each fillable pair returns ``[a, mid, b]`` where ``b`` is the SAME key as the
    next pair's ``a`` (the shared artist key). Naively flattening duplicates that
    boundary key — every kept frame appears twice in a row, a held-then-jump
    stutter that also inflates the clip ~1.5x. So we drop the leading frame of a
    pair when it equals the last frame already emitted. Intentional *intra*-pair
    holds (``[a, a, b]`` on-2s cadence) are preserved — only cross-pair shared
    endpoints are dropped. ``needs_key`` pairs contribute nothing, leaving a
    genuine gap (the segments either side are not contiguous, so no dedup)."""
    out: List[np.ndarray] = []
    for p in result.pairs:
        if p.action not in ("filled", "generated") or not p.frames:
            continue
        frames = [(fr if isinstance(fr, np.ndarray) else np.array(fr, dtype=np.uint8)).astype(np.uint8)
                  for fr in p.frames]
        start = 1 if (out and np.array_equal(out[-1], frames[0])) else 0
        out.extend(frames[start:])
    return out


def build_video(result: CopilotResult, out_dir: str, fps: int = 24) -> str:
    """Write reconstructed.mp4 (browser-playable **H.264/yuv420p** via imageio+ffmpeg)
    from the filled/generated pairs. cv2 `mp4v` is not decodable in browsers, so we
    encode libx264 — matching .scratch/copilot/demo_copilot.py.

    ``fps`` defaults to 24: the reconstruction restores a stride-2-decimated cut to
    full frame-rate, so it must play at the source rate (~23.976/24fps). The old
    default of 12 played a full-rate reconstruction at 2x slow-motion."""
    import imageio

    path = os.path.join(out_dir, "reconstructed.mp4")

    # collect all frames (only filled / generated pairs contribute), dropping the
    # shared key duplicated at each pair boundary
    all_frames: List[np.ndarray] = _assemble_frames(result)

    if not all_frames:
        # nothing to write — a small black placeholder so the file exists
        all_frames = [np.zeros((16, 16, 3), np.uint8)]

    # H.264 + yuv420p need EVEN dimensions; crop to even (macro_block_size=None = no auto-pad)
    h, w = all_frames[0].shape[:2]
    h2, w2 = h - (h % 2), w - (w % 2)
    frames = [f[:h2, :w2] for f in all_frames]
    imageio.mimwrite(path, frames, fps=fps, codec="libx264",
                     pixelformat="yuv420p", macro_block_size=None)
    return path


def save_pair_mid(pair, out_dir: str) -> "str | None":
    """Save ONE pair's in-between (mid) frame as ``pair_<idx>.png`` and return the
    filename (or ``None`` for needs_key / frameless pairs). Called per-pair in the
    worker's on_pair so the in-between streams live as each pair arrives — the UI's
    right column / line-test does not have to wait for the final result event."""
    if pair.action not in ("filled", "generated") or not pair.frames:
        return None
    mid = pair.frames[len(pair.frames) // 2]
    mid = mid if isinstance(mid, np.ndarray) else np.array(mid, dtype=np.uint8)
    fname = f"pair_{pair.index}.png"
    Image.fromarray(mid.astype(np.uint8)).save(os.path.join(out_dir, fname))
    return fname


def build_pair_frames(result: CopilotResult, out_dir: str) -> "dict[int, str]":
    """Save each filled/generated pair's in-between; return ``{pair_index: filename}``
    (the final-result fallback; live per-pair saving is `save_pair_mid` in on_pair)."""
    out: "dict[int, str]" = {}
    for p in result.pairs:
        fn = save_pair_mid(p, out_dir)
        if fn is not None:
            out[p.index] = fn
    return out
