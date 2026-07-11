"""Tests for service.media.artifacts — build_montage, build_video, build_report."""
import inspect
import os
import numpy as np

from service.media.artifacts import build_montage, build_video, build_report, _assemble_frames, build_pair_frames
from inbetween_copilot.pipeline.copilot import PairResult, CopilotResult
from inbetween_copilot.qa.gate import FrameQA


def _frame(v):
    return np.full((4, 4, 3), v, np.uint8)

# NOTE: FrameQA is a frozen dataclass with fields (status, reason) — two required args.
# The prompt showed FrameQA(status="pass") but that omits `reason`.
# Real constructor: FrameQA(status="pass", reason="")


def _res():
    fr = [np.zeros((8, 8, 3), np.uint8) for _ in range(3)]
    p = PairResult(0, "filled", "rife", fr, FrameQA(status="pass", reason=""), 0)
    return CopilotResult(pairs=[p], keys_requested_total=0, flagged=[], n_autopass=1)


def test_build_pair_frames_saves_mid_for_filled(tmp_path):
    """A filled pair's in-between (mid frame) is saved as pair_<idx>.png and mapped."""
    r = _res()
    out = build_pair_frames(r, str(tmp_path))
    assert out == {0: "pair_0.png"}
    p = os.path.join(str(tmp_path), "pair_0.png")
    assert os.path.getsize(p) > 0
    with open(p, "rb") as fh:
        assert fh.read(4) == b"\x89PNG"


def test_build_pair_frames_skips_needs_key(tmp_path):
    """needs_key pairs have no in-between -> not saved, not in the map."""
    pk = PairResult(0, "needs_key", None, None, None, 1)
    r = CopilotResult(pairs=[pk], keys_requested_total=1, flagged=[], n_autopass=0)
    out = build_pair_frames(r, str(tmp_path))
    assert out == {}
    assert not os.path.exists(os.path.join(str(tmp_path), "pair_0.png"))


def test_artifacts_write_files(tmp_path):
    r = _res()
    keys = [np.zeros((8, 8, 3), np.uint8) for _ in range(2)]
    m   = build_montage(r, keys, str(tmp_path))
    v   = build_video(r, str(tmp_path))
    rep = build_report(r, str(tmp_path))
    assert os.path.getsize(m) > 0
    assert os.path.getsize(v) > 0
    assert os.path.getsize(rep) > 0


def test_report_contains_summary(tmp_path):
    r = _res()
    rep = build_report(r, str(tmp_path))
    text = open(rep, encoding="utf-8").read()
    assert "auto-pass" in text


def test_report_contains_cadence_badge(tmp_path):
    r = _one_pair_result()
    path = build_report(r, str(tmp_path), cadence_fps=12, smoothness=2, output_fps=24, duration=2.0)
    text = open(path, encoding="utf-8").read()
    assert "×2" in text and "on-2s" in text and "24" in text and "2.0" in text


def test_montage_is_png(tmp_path):
    r = _res()
    keys = [np.zeros((8, 8, 3), np.uint8) for _ in range(2)]
    m = build_montage(r, keys, str(tmp_path))
    assert m.endswith(".png")
    # PNG magic bytes
    with open(m, "rb") as fh:
        assert fh.read(4) == b"\x89PNG"


def test_video_file_exists(tmp_path):
    r = _res()
    v = build_video(r, str(tmp_path))
    assert os.path.exists(v) and v.endswith(".mp4")


def test_montage_with_regions_writes_png_nonzero(tmp_path):
    """build_montage with regions= draws a red box and still outputs a valid PNG."""
    r = _res()
    keys = [np.zeros((8, 8, 3), np.uint8) for _ in range(2)]
    # pair index 0 has region (1, 1, 5, 5) on the mid cell
    m = build_montage(r, keys, str(tmp_path), regions={0: (1, 1, 5, 5)})
    assert os.path.getsize(m) > 0
    with open(m, "rb") as fh:
        assert fh.read(4) == b"\x89PNG"


def test_montage_without_regions_unchanged(tmp_path):
    """build_montage with regions=None (default) still works."""
    r = _res()
    keys = [np.zeros((8, 8, 3), np.uint8) for _ in range(2)]
    m = build_montage(r, keys, str(tmp_path))
    assert os.path.getsize(m) > 0


# --- reconstructed-video frame assembly (real-time playback fix) ---

def test_assemble_dedupes_shared_boundary_frame():
    """Pair i ends on key_{i+1} and pair i+1 starts on the same key -> the shared
    boundary frame must appear ONCE, not twice (the stutter bug)."""
    a, m1, b, m2, c = (_frame(v) for v in (10, 20, 30, 40, 50))
    p0 = PairResult(0, "filled", "rife", [a, m1, b], FrameQA(status="pass", reason=""), 0)
    p1 = PairResult(1, "filled", "rife", [b, m2, c], FrameQA(status="pass", reason=""), 0)
    r = CopilotResult(pairs=[p0, p1], keys_requested_total=0, flagged=[], n_autopass=2)
    frames = _assemble_frames(r)
    assert len(frames) == 5  # a, m1, b, m2, c  (b not duplicated)
    assert [int(f[0, 0, 0]) for f in frames] == [10, 20, 30, 40, 50]


def test_assemble_preserves_intra_pair_hold():
    """A held drawing [a, a, b] is intentional on-2s cadence -> the internal
    duplicate is kept; only shared cross-pair endpoints are dropped."""
    a, b = _frame(10), _frame(30)
    p = PairResult(0, "filled", "hold", [a, a, b], FrameQA(status="pass", reason=""), 0)
    r = CopilotResult(pairs=[p], keys_requested_total=0, flagged=[], n_autopass=1)
    frames = _assemble_frames(r)
    assert len(frames) == 3
    assert [int(f[0, 0, 0]) for f in frames] == [10, 10, 30]


def test_assemble_keeps_distinct_segments_across_needs_key_gap():
    """A needs_key pair contributes no frames; the segments on either side are not
    contiguous (b != c) so nothing is deduped across the gap."""
    a, m, b, c, m2, d = (_frame(v) for v in (10, 20, 30, 60, 70, 80))
    p0 = PairResult(0, "filled", "rife", [a, m, b], FrameQA(status="pass", reason=""), 0)
    pk = PairResult(1, "needs_key", None, None, None, 1)
    p2 = PairResult(2, "filled", "rife", [c, m2, d], FrameQA(status="pass", reason=""), 0)
    r = CopilotResult(pairs=[p0, pk, p2], keys_requested_total=1, flagged=[], n_autopass=2)
    frames = _assemble_frames(r)
    assert len(frames) == 6  # b(30) != c(60) -> no dedup across the gap


def test_build_video_default_fps_is_24():
    """Stride-2 reconstruction is full-rate -> default playback must match a
    ~24fps source, not the old 12fps (which played at 2x slow-motion)."""
    assert inspect.signature(build_video).parameters["fps"].default == 24


# --- display-depth (Smoothness Control): factor/mid_engine threaded through assembly ---

def _one_pair_result(route="rife"):
    """Minimal single filled pair [a, mid, b], built the same way as `_res()`/the
    boundary-dedup tests above (distinct per-frame values via `_frame(v)`)."""
    a, m, b = (_frame(v) for v in (10, 20, 30))
    p = PairResult(0, "filled", route, [a, m, b], FrameQA(status="pass", reason=""), 0)
    return CopilotResult(pairs=[p], keys_requested_total=0, flagged=[], n_autopass=1)


def test_assemble_factor2_matches_default():
    """factor=2 is the default depth -> must reproduce today's output byte-for-byte."""
    r = _one_pair_result()
    base = _assemble_frames(r)
    fac2 = _assemble_frames(r, factor=2)
    assert [f.tolist() for f in base] == [f.tolist() for f in fac2]


def test_assemble_off_drops_mid():
    """factor=1 (Off) keeps only the artist keys [a, b] -> mid frame dropped."""
    r = _one_pair_result()
    off = _assemble_frames(r, factor=1)
    assert len(off) == 2


# --- M2: build_video(frames=...) reuses a pre-assembled list instead of re-assembling ---

def test_build_video_with_frames_skips_internal_assembly(monkeypatch, tmp_path):
    """When `frames=` is provided, build_video must use it directly and NOT call
    `_assemble_frames` internally (M2 fix — at smoothness=4 each re-assembly re-runs
    the GPU mid_engine per rife pair, so assembling twice per session wastes a full
    RIFE pass). Monkeypatch `_assemble_frames` to blow up if invoked."""
    import service.media.artifacts as artifacts_mod

    def _boom(*a, **k):
        raise AssertionError("_assemble_frames must not be called when frames= is given")
    monkeypatch.setattr(artifacts_mod, "_assemble_frames", _boom)

    r = _res()
    preassembled = [_frame(1), _frame(2), _frame(3)]
    v = build_video(r, str(tmp_path), frames=preassembled)
    assert os.path.exists(v) and os.path.getsize(v) > 0


def test_build_video_with_frames_encodes_exact_list(tmp_path):
    """build_video(frames=preassembled) encodes exactly the passed frames, not
    whatever `_assemble_frames(result, ...)` would independently compute (here the
    `result` has a DIFFERENT single pair, so if build_video ignored `frames` and
    reassembled from `result` instead, the frame count/content would differ)."""
    import imageio.v2 as imageio

    r = _res()   # a single filled pair -> _assemble_frames(r) would yield 3 frames
    preassembled = [_frame(v) for v in (7, 8, 9, 10)]   # a distinct 4-frame list
    v = build_video(r, str(tmp_path), frames=preassembled)
    read_back = imageio.mimread(v)
    assert len(read_back) == 4   # matches `frames`, not the 3 `_assemble_frames(r)` would give


def test_build_video_default_still_assembles_internally(tmp_path):
    """Back-compat: frames=None (the default) preserves today's behaviour —
    build_video assembles from `result` itself."""
    r = _res()
    v = build_video(r, str(tmp_path))
    assert os.path.exists(v) and os.path.getsize(v) > 0
