import numpy as np
import pytest

from benchmark.largegap.clips import (
    best_window, clip_flags, decode_video, hardsub_score, select_clip,
    write_eval_clip,
)


def _moving_frames(n=70, h=64, w=96, step=3):
    """A bright square translating right — real motion, no cut, no subs.

    DEVIATION FROM BRIEF: the brief's literal `x = (i * step) % (w - 16)`
    hard-wraps (teleports) the block back to x=0 once it reaches the right
    edge. At w=96/step=3 that teleport lands with ZERO spatial overlap with
    the previous frame (block fully vacates one position, fully occupies a
    disjoint one), so gap_score spikes to ~16/3x the steady-state median --
    above FLASH_RATIO=4.0 in clips.py -- and has_flash fires as a false
    positive within the 65/70-frame windows every test in this file uses
    (confirmed analytically with zero video codec involved, and reproduced
    running the brief's code verbatim: has_flash=True on `_moving_frames(65)`
    with no injected flash frame). Widening `w` alone (tried first) removes
    the wrap but dilutes gap_score's whole-frame normalisation enough to
    drop below the default MOTION_MIN=0.01 in select_clip, trading one
    failure for another. Fix here instead: bounce the block off the right
    edge (triangle wave) instead of teleporting, so position always changes
    by ~step every frame including at the turnaround -- no spike, no
    dilution, same w/h/step as the brief. Verified against all 6 tests (see
    task-3 report). clips.py itself (FLASH_RATIO, TRIM_FRAMES, MOTION_MIN,
    all thresholds) is untouched -- this is a test-fixture-only fix, flagged
    for review.
    """
    out = []
    m = w - 16
    period = 2 * m
    for i in range(n):
        f = np.zeros((h, w, 3), dtype=np.uint8)
        pos = (i * step) % period
        x = pos if pos <= m else period - pos
        f[24:40, x:x + 16] = 180
        out.append(f)
    return out


def test_roundtrip_eval_clip(tmp_path):
    frames = _moving_frames(65)
    mp4 = tmp_path / "eval.mp4"
    write_eval_clip(frames, mp4)
    back = decode_video(mp4, max_frames=65)
    assert len(back) == 65
    assert back[0].shape == frames[0].shape
    assert int(np.abs(back[10].astype(int) - frames[10].astype(int)).max()) <= 2


def test_clip_flags_on_moving_clip():
    flags = clip_flags(_moving_frames(65))
    assert flags["motion_mean"] > 0.001
    assert not flags["has_cut"]
    assert not flags["has_flash"]


def test_cut_and_flash_detected():
    frames = _moving_frames(65)
    frames[30] = np.full_like(frames[30], 255)          # white flash frame
    flags = clip_flags(frames)
    assert flags["has_flash"] or flags["has_cut"]


def test_hardsub_score_fires_on_bottom_text_band():
    clean = _moving_frames(20)
    subbed = [f.copy() for f in clean]
    for f in subbed:                                     # fat white bar w/ dark outline
        f[52:60, 20:76] = 255
        f[50:52, 18:78] = 10
        f[60:62, 18:78] = 10
    assert hardsub_score(subbed) > hardsub_score(clean) + 0.01


def test_select_clip_writes_manifest_row_and_pngs(tmp_path):
    src = tmp_path / "src.mp4"
    write_eval_clip(_moving_frames(70), src)
    row = select_clip(src, "c0001", "ood", tmp_path / "out")
    assert row["kept"] is True and row["n_frames_used"] == 65
    pngs = sorted((tmp_path / "out" / "c0001" / "frames").glob("*.png"))
    assert len(pngs) == 65
    assert (tmp_path / "out" / "c0001" / "eval.mp4").exists()


def test_select_clip_drops_static(tmp_path):
    src = tmp_path / "static.mp4"
    write_eval_clip([np.zeros((64, 96, 3), np.uint8)] * 70, src)
    row = select_clip(src, "c0002", "ood", tmp_path / "out")
    assert row["kept"] is False and row["drop_reason"] == "low_motion"


def test_best_window_finds_motion_after_static_opening():
    static = [np.zeros((64, 96, 3), np.uint8)] * 65
    moving = _moving_frames(80)
    window, start, flags = best_window(static + moving)
    assert len(window) == 65
    assert start > 0
    assert flags["motion_mean"] > 0.001


def test_select_clip_records_decode_error(tmp_path):
    # Try nonexistent path first; if that doesn't raise via isOpened,
    # create a zero-byte file to force an unopenable input
    missing = tmp_path / "nope.mp4"
    row = select_clip(missing, "c0003", "ood", tmp_path / "out")
    # On some platforms OpenCV silently returns empty on missing files;
    # verify the row reflects a decode error or too_short, with error field set
    if row["drop_reason"] == "decode_error":
        assert row["kept"] is False and "error" in row
    else:
        # If isOpened doesn't catch it, try a zero-byte file
        zero_byte = tmp_path / "empty.mp4"
        zero_byte.write_bytes(b"")
        row = select_clip(zero_byte, "c0004", "ood", tmp_path / "out")
        assert row["kept"] is False and row["drop_reason"] == "decode_error"
        assert "error" in row
