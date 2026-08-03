"""The marked image must reach the browser, and it must LOOK different.

`annotate_explained_pairs` is well covered on its own, and the agent refuses to
offer `show_annotated` unless an annotated render exists. Neither of those
noticed that the client never read `annotated_url`: the artist asked to see where
the error was, was told "Showing the marked frame for pair 2", and got an
ordinary in-between. These pin the whole chain the review board now depends on —
render, URL, route, and that the served bytes actually carry a mark.
"""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from inbetween_copilot.qa.models import FrameQA
from service.app import app
from service.media.rendering import render_session_artifacts
from service.sessions.presentation import build_render_metadata
from service.sessions.schemas import SessionCfg
from service.sessions.dependencies import default_session_repository


class _Pair:
    def __init__(self, index, frames):
        self.index = index
        self.action = "filled"
        self.route = "rife"
        self.frames = frames
        # explain_pairs only looks at flagged/abstained pairs; a `pass` pair has
        # no finding and therefore no marked image, which is the whole point.
        self.qa = FrameQA(status="abstain", reason="csq: p=0.44 u=0.31",
                          p_error=0.44, u=0.31)
        self.keys_requested = 0
        self.correction = None
        self.triage = None
        self.artist_verdict = None


class _Result:
    def __init__(self, pairs):
        self.pairs = pairs
        self.n_autopass = 0
        self.n_corrected = 0
        self.flagged = [0]
        self.abstained = []
        self.keys_requested_total = 0


def _drawing(shift: int = 0, size: int = 96) -> np.ndarray:
    frame = np.full((size, size, 3), 245, np.uint8)
    frame[30:60, 20 + shift:50 + shift] = 20
    return frame


class _Bundle:
    """Only what the renderer reads off the engine bundle."""

    vlm_status: dict = {}
    csq_calibrator = None


def _render(tmp_path):
    keys = [_drawing(0), _drawing(2)]
    frames = [_drawing(0), _drawing(1), _drawing(2)]
    result = _Result([_Pair(0, frames)])
    rendered = render_session_artifacts(
        result, keys, str(tmp_path),
        cadence_fps=12, smoothness=2, output_fps=24,
        mid_engine=None,
        # A flagged pair with a pinned region: exactly the case the artist hit.
        vlm_struct_fn=lambda *a, **k: {
            "has_error": True, "err_type": "ghosting", "region_hint": "mc",
            "explanation": "a doubled outline across the forearm", "softness": 0.2,
        },
        softness_fn=lambda *a, **k: 0.2,
    )
    return result, rendered


def test_the_render_publishes_an_annotated_url_for_an_explained_pair(tmp_path):
    result, rendered = _render(tmp_path)
    assert rendered.annotated_files, "no marked image was rendered for a flagged pair"
    metadata = build_render_metadata(
        7, rendered, SessionCfg(engines="stub"), _Bundle(), base_sampling=None)
    explanation = metadata.explanations[0]
    # The review board reads exactly this field; without it the board has nothing
    # to show and "Show marked image" is a promise the client cannot keep.
    assert explanation["annotated_url"] == "/session/7/pair_0_annotated.png"
    assert (tmp_path / "pair_0_annotated.png").exists()


def test_the_marked_frame_is_served_and_differs_from_the_clean_one(tmp_path):
    """Serving an identical image would still show the artist nothing."""
    _render(tmp_path)
    sid = 424242
    default_session_repository.register_path(sid, str(tmp_path))
    try:
        client = TestClient(app)
        marked = client.get(f"/session/{sid}/pair_0_annotated.png")
        clean = client.get(f"/session/{sid}/pair_0.png")
        assert marked.status_code == 200, marked.text
        assert clean.status_code == 200, clean.text
        assert marked.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert marked.content != clean.content, (
            "the marked render is byte-identical to the plain in-between, so the "
            "artist would still see nothing"
        )
    finally:
        default_session_repository.paths.pop(sid, None)
        default_session_repository.states.pop(sid, None)


def test_the_mark_is_red_ink_the_drawing_does_not_contain(tmp_path):
    """The line art is greyscale; the QA mark is the only red in the frame."""
    _render(tmp_path)
    from PIL import Image

    marked = np.array(Image.open(tmp_path / "pair_0_annotated.png").convert("RGB"))
    clean = np.array(Image.open(tmp_path / "pair_0.png").convert("RGB"))
    red = (marked[..., 0].astype(int) - marked[..., 1].astype(int)) > 120
    assert red.any(), "no red mark was burnt into the frame"
    assert not ((clean[..., 0].astype(int) - clean[..., 1].astype(int)) > 120).any()
