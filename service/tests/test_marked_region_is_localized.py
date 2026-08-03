"""The mark must point at the defect, not draw a ring around the drawing.

The artist asked where the error was, got a red rectangle around the whole
frame, and said so: *"nó chỉ khoanh xung quanh chứ không phải vùng lỗi"*.

The region came from the VLM's coarse 3x3 hint alone — and ADR-0012 already
records that the VLM at 320 px is detail-blind and its spatial localization is
deferred. Meanwhile `localize_softness` (ADR-0011, shipping inside the
correction loop) measures WHERE the interpolated frame went soft against its own
source frames, reference-free and on a 4x4 grid. The explainability path never
called it.
"""
from __future__ import annotations

import numpy as np
import pytest

from inbetween_copilot.qa.models import FrameQA
from service.media.annotate import annotate_explained_pairs, annotate_frame
from service.media.explain import explain_pairs


def _strokes(size=128, seed=1):
    """Crisp line art: sharpness is what the localizer measures."""
    rng = np.random.default_rng(seed)
    frame = np.full((size, size, 3), 245, np.uint8)
    for _ in range(60):
        y, x = rng.integers(4, size - 24, 2)
        frame[y:y + 2, x:x + 22] = 20
        frame[y:y + 22, x:x + 2] = 20
    return frame


def _blur(frame, y0, y1, x0, x1, k=7):
    out = frame.copy().astype(float)
    patch = out[y0:y1, x0:x1]
    kernel = np.ones(k) / k
    for channel in range(3):
        for axis in (0, 1):
            patch[:, :, channel] = np.apply_along_axis(
                lambda m: np.convolve(m, kernel, "same"), axis, patch[:, :, channel])
    out[y0:y1, x0:x1] = patch
    return out.astype(np.uint8)


class _Pair:
    def __init__(self, index, frames):
        self.index = index
        self.action = "filled"
        self.frames = frames
        self.qa = FrameQA(status="abstain", reason="", p_error=0.5, u=0.3)


class _Result:
    def __init__(self, pairs):
        self.pairs = pairs


def _bottom_left_blur_pair():
    a = _strokes()
    b = _strokes()
    mid = _blur(((a.astype(int) + b.astype(int)) // 2).astype(np.uint8), 64, 128, 0, 64)
    return _Result([_Pair(0, [a, mid, b])])


def _clean_vlm(*_args, **_kwargs):
    """The observed production case: the VLM sees nothing and pins nothing, and
    the pair is held back by the calibrated softness channel instead."""
    return {"has_motion_error": False, "error_type": "none", "region": "none",
            "explanation": "real animation, clean coherent motion"}


def test_the_explanation_carries_measured_tiles_not_just_the_vlm_hint():
    result = _bottom_left_blur_pair()
    explained = explain_pairs(
        result, vlm_struct_fn=_clean_vlm, softness_fn=lambda frames: 0.4)
    entry = explained[0]
    assert entry["region"] == "none", "the VLM pinned nothing, as observed live"
    tiles = entry.get("region_tiles")
    assert tiles, "no measured region: the mark can only be a whole-frame ring"
    assert tiles["grid"] == 4
    # every tile the localizer picked must lie in the quadrant that is blurred
    assert all(row >= 2 and col <= 1 for row, col in tiles["mask"]), tiles


def test_the_mark_lands_on_the_blurred_quadrant_and_not_the_sharp_one(tmp_path):
    result = _bottom_left_blur_pair()
    explained = explain_pairs(
        result, vlm_struct_fn=_clean_vlm, softness_fn=lambda frames: 0.4)
    files = annotate_explained_pairs(result, explained, str(tmp_path))
    assert files == {0: "pair_0_annotated.png"}

    from PIL import Image
    marked = np.array(Image.open(tmp_path / "pair_0_annotated.png").convert("RGB"))
    red = (marked[..., 0].astype(int) - marked[..., 1].astype(int)) > 120
    # below the label chip strip, red ink must appear ONLY in the blurred corner
    body = red[26:, :]
    bottom_left = body[body.shape[0] // 2:, : body.shape[1] // 2]
    top_right = body[: body.shape[0] // 2, body.shape[1] // 2:]
    assert bottom_left.any(), "the defect quadrant was not marked"
    assert not top_right.any(), (
        "red ink in the sharp quadrant: the mark is still ringing the whole frame")


def test_an_unlocalizable_pair_says_so_instead_of_claiming_the_whole_frame():
    """`region: none` means the VLM pinned nothing. Rendering that as `@ whole`
    asserts the defect spans the frame — a different, unearned claim."""
    frame = _strokes()
    marked = annotate_frame(frame, "none", "blur", tiles=None)
    from PIL import Image
    text_strip = np.array(Image.fromarray(marked))[:26]
    assert (text_strip == 0).all(axis=2).any(), "no label chip was drawn"
    # the label is checked through the public helper so the wording stays pinned
    from service.media.annotate import region_label
    assert region_label("none", None) == "not pinned"
    assert region_label("whole", None) == "whole"
    assert region_label("none", {"grid": 4, "mask": [(3, 0), (3, 1)]}) == "2 soft tiles"
