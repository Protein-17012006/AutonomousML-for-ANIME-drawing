"""Tests for service.media.demo — decimate-vs-GT side-by-side comparison video (web demo-mode)."""
import os

import cv2
import numpy as np
import pytest

from service.media.demo import build_demo_videos
from service.infrastructure.engines import stub_engines
from service.sessions.schemas import SessionCfg


def _frame(v):
    return np.full((16, 24, 3), v, np.uint8)


def test_stub_engines_exposes_rife_engine():
    eng = stub_engines(SessionCfg())
    assert eng.rife_engine is not None
    out = eng.rife_engine(_frame(0), _frame(100))
    assert len(out) == 3 and out[1].shape == (16, 24, 3)   # [a, mid, b]


def test_demo_compare_video_decimates_and_encodes(tmp_path):
    """compare.mp4 geometry+fps out of build_demo_videos. (build_comparison_video,
    the single-video predecessor, was deleted 2026-07-08 — build_demo_videos is
    the one production entry; same _decimate_rife/_encode_h264 path.)"""
    rife = stub_engines(SessionCfg()).rife_engine
    full = [_frame(v) for v in (10, 30, 50, 70, 90, 110, 130)]   # 7 frames
    build_demo_videos(full, rife, str(tmp_path), fps=24)
    path = os.path.join(str(tmp_path), "compare.mp4")
    assert os.path.exists(path)
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = round(cap.get(cv2.CAP_PROP_FPS), 3)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    cap.release()
    # 7 full -> src=4 (idx 0,2,4,6), gt=3 -> comparison length 2*4-1 = 7
    assert n == 7 and fps == 24
    assert w == 24 + 4 + 24       # left | 4px divider | right


def test_demo_videos_need_min_frames(tmp_path):
    rife = stub_engines(SessionCfg()).rife_engine
    with pytest.raises(ValueError):
        build_demo_videos([_frame(0), _frame(50)], rife, str(tmp_path))


def test_build_demo_videos_writes_split_full_frame_cuts(tmp_path):
    """One pass -> compare.mp4 (side-by-side) + original.mp4 + recon.mp4 (full-frame),
    the two separate cuts the client before/after wipe plays stacked."""
    rife = stub_engines(SessionCfg()).rife_engine
    full = [_frame(v) for v in (10, 30, 50, 70, 90, 110, 130)]   # 7 frames
    names = build_demo_videos(full, rife, str(tmp_path), fps=24)
    assert names == {"video": "compare.mp4", "original": "original.mp4", "recon": "recon.mp4"}
    for key, name in names.items():
        assert os.path.exists(os.path.join(tmp_path, name))
    # the split cuts are FULL-frame (no divider): width == source 24, length == 2*4-1 == 7
    for name in ("original.mp4", "recon.mp4"):
        cap = cv2.VideoCapture(os.path.join(str(tmp_path), name))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cap.release()
        assert n == 7 and w == 24       # no side-by-side divider
