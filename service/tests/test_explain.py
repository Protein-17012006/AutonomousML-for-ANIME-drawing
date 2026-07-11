"""Tests for service.media.explain — pure, box-free.

RED phase: all tests fail because service/explain.py does not exist yet.
"""
from __future__ import annotations

import numpy as np
import pytest

from inbetween_copilot.pipeline.copilot import PairResult, CopilotResult
from inbetween_copilot.qa.gate import FrameQA


# ---------------------------------------------------------------------------
# region_box tests
# ---------------------------------------------------------------------------

def test_region_box_br():
    from service.media.explain import region_box
    assert region_box("br", 300, 300) == (200, 200, 300, 300)


def test_region_box_whole():
    from service.media.explain import region_box
    assert region_box("whole", 9, 9) == (0, 0, 9, 9)


def test_region_box_none_returns_none():
    from service.media.explain import region_box
    assert region_box("none", 9, 9) is None


def test_region_box_unknown_returns_none():
    from service.media.explain import region_box
    assert region_box("bad_hint", 10, 10) is None


def test_region_box_tl():
    from service.media.explain import region_box
    assert region_box("tl", 90, 60) == (0, 0, 30, 20)


def test_region_box_mc():
    from service.media.explain import region_box
    assert region_box("mc", 90, 60) == (30, 20, 60, 40)


def test_region_box_tr():
    from service.media.explain import region_box
    assert region_box("tr", 90, 60) == (60, 0, 90, 20)


# ---------------------------------------------------------------------------
# explain_pairs tests
# ---------------------------------------------------------------------------

def _make_frames():
    return [np.zeros((8, 8, 3), np.uint8) for _ in range(3)]


def _stub_vlm_struct(frames):
    """A deterministic structured VLM stub that always returns a ghost error."""
    return {
        "has_motion_error": True,
        "error_type": "ghost",
        "region": "mc",
        "explanation": "stub: ghost in centre",
    }


def _zero_softness(frames):
    return 0.0


def test_explain_pairs_flags_flagged_pair():
    """A pair with qa.status='flag' and frames present → appears in result."""
    from service.media.explain import explain_pairs

    frames = _make_frames()
    flagged_pair = PairResult(
        index=0,
        action="filled",
        route="rife",
        frames=frames,
        qa=FrameQA(status="flag", reason="detector"),
        keys_requested=0,
    )
    result = CopilotResult(
        pairs=[flagged_pair],
        keys_requested_total=0,
        flagged=[0],
        n_autopass=0,
    )

    out = explain_pairs(result, vlm_struct_fn=_stub_vlm_struct, softness_fn=_zero_softness)

    assert 0 in out
    assert out[0]["err_type"] == "ghost"
    assert out[0]["region"] == "mc"
    assert "stub" in out[0]["explanation"]


def test_explain_pairs_flags_abstained_pair():
    """A pair with qa.status='abstain' also appears in result."""
    from service.media.explain import explain_pairs

    frames = _make_frames()
    abstained_pair = PairResult(
        index=2,
        action="generated",
        route="generative",
        frames=frames,
        qa=FrameQA(status="abstain", reason="csq:abstain"),
        keys_requested=0,
    )
    result = CopilotResult(
        pairs=[abstained_pair],
        keys_requested_total=0,
        flagged=[],
        n_autopass=0,
        abstained=[2],
    )

    out = explain_pairs(result, vlm_struct_fn=_stub_vlm_struct, softness_fn=_zero_softness)
    assert 2 in out


def test_explain_pairs_skips_pass_pair():
    """A pair with qa.status='pass' must not appear in the result dict."""
    from service.media.explain import explain_pairs

    frames = _make_frames()
    pass_pair = PairResult(
        index=1,
        action="filled",
        route="rife",
        frames=frames,
        qa=FrameQA(status="pass", reason=""),
        keys_requested=0,
    )
    result = CopilotResult(
        pairs=[pass_pair],
        keys_requested_total=0,
        flagged=[],
        n_autopass=1,
    )

    out = explain_pairs(result, vlm_struct_fn=_stub_vlm_struct, softness_fn=_zero_softness)
    assert 1 not in out


def test_explain_pairs_skips_needs_key_pair():
    """A pair with action='needs_key' (frames=None) must be skipped."""
    from service.media.explain import explain_pairs

    needs_key_pair = PairResult(
        index=3,
        action="needs_key",
        route=None,
        frames=None,
        qa=None,
        keys_requested=1,
    )
    result = CopilotResult(
        pairs=[needs_key_pair],
        keys_requested_total=1,
        flagged=[],
        n_autopass=0,
    )

    out = explain_pairs(result, vlm_struct_fn=_stub_vlm_struct, softness_fn=_zero_softness)
    assert 3 not in out


def test_explain_pairs_mixed_skips_pass_keeps_flag():
    """Mixed result: pass pair skipped, flag pair present."""
    from service.media.explain import explain_pairs

    frames = _make_frames()
    pass_pair = PairResult(0, "filled", "rife", frames,
                           FrameQA(status="pass", reason=""), 0)
    flag_pair = PairResult(1, "filled", "rife", frames,
                           FrameQA(status="flag", reason="detector"), 0)
    result = CopilotResult(pairs=[pass_pair, flag_pair],
                           keys_requested_total=0, flagged=[1], n_autopass=1)

    out = explain_pairs(result, vlm_struct_fn=_stub_vlm_struct, softness_fn=_zero_softness)
    assert 0 not in out
    assert 1 in out
