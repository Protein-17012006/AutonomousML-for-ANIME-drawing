"""Port-fidelity tests for Long's DiffuEraser span maths.

Each test pins a NUMBER carried over from
`scripts/run_diffueraser_repair.py` on the 5090 box, not merely a shape. A port
that "looks similar" but drops the 8-px grid, the 96-px padding floor, the
12-frame context or the 0.8 blur sigma must go RED here — those constants decide
what the diffusion model is actually asked to reconstruct.
"""
from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from PIL import Image

from service.image_edit.span import (
    MIN_CONTEXT_FRAMES,
    aligned_crop,
    compose_frame,
    context_bounds,
    decode_mask,
    process_size,
)


def _mask(height: int, width: int, box) -> np.ndarray:
    """A 0/255 mask with one filled rectangle, given as (y0, y1, x0, x1)."""
    canvas = np.zeros((height, width), np.uint8)
    y0, y1, x0, x1 = box
    canvas[y0:y1, x0:x1] = 255
    return canvas


def _png_bytes(array: np.ndarray, mode: str) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array, mode=mode).save(buffer, format="PNG")
    return buffer.getvalue()


# --- aligned_crop -----------------------------------------------------------

def test_aligned_crop_snaps_both_edges_to_the_eight_grid():
    # The diffusion VAE downsamples by 8. An unaligned crop asks the model to
    # reconstruct across a phase-shifted boundary.
    x0, y0, x1, y1 = aligned_crop(_mask(512, 512, (201, 203, 101, 105)), 512, 512)
    assert x0 % 8 == 0 and y0 % 8 == 0
    assert x1 % 8 == 0 and y1 % 8 == 0


def test_aligned_crop_uses_the_ninety_six_pixel_floor_for_a_small_box():
    # padding = max(96, round(0.3 * longer side)); a 4x2 box takes the floor,
    # so the crop is the box grown by 96 and then snapped outward.
    assert aligned_crop(_mask(512, 512, (200, 202, 100, 104)), 512, 512) == (
        0, 104, 200, 304)


def test_aligned_crop_uses_thirty_percent_when_the_box_is_large():
    # A 400-wide box pads by 120, not 96. Pinning this is what separates the
    # real rule from a hardcoded 96.
    x0, _y0, x1, _y1 = aligned_crop(_mask(1024, 1024, (10, 20, 100, 500)), 1024, 1024)
    assert x0 == 0                                   # 100 - 120 clamps to 0
    assert x1 == ((100 + 400 + 120 + 7) // 8) * 8    # 624


def test_aligned_crop_clamps_inside_the_frame():
    assert aligned_crop(_mask(64, 64, (0, 64, 0, 64)), 64, 64) == (0, 0, 64, 64)


def test_aligned_crop_refuses_an_empty_mask():
    with pytest.raises(ValueError):
        aligned_crop(np.zeros((32, 32), np.uint8), 32, 32)


# --- process_size -----------------------------------------------------------

def test_process_size_bounds_to_960_by_540_on_the_eight_grid():
    width, height = process_size(1920, 1080)
    assert width <= 960 and height <= 540
    assert width % 8 == 0 and height % 8 == 0


def test_process_size_bounds_a_wide_short_crop_by_its_WIDTH():
    # 1920x1080 is bounded by the HEIGHT cap, so it cannot pin the width cap at
    # all: raising MAX_PROCESS_WIDTH to 1920 left the suite green. A wide, short
    # crop is the only shape where the width cap is the one doing the work.
    assert process_size(1920, 200) == (960, 96)


def test_process_size_bounds_a_tall_narrow_crop_by_its_HEIGHT():
    # The mirror of the above, and it was missing for the same reason: on every
    # shape tested so far the WIDTH cap bound first, so raising
    # MAX_PROCESS_HEIGHT to 1080 also left the suite green.
    assert process_size(200, 1080) == (96, 536)


def test_process_size_never_upscales():
    assert process_size(320, 240) == (320, 240)


def test_process_size_floors_at_sixty_four():
    assert process_size(8, 8) == (64, 64)


# --- context_bounds ---------------------------------------------------------

def test_context_bounds_takes_twelve_real_neighbours_each_side():
    # This is the whole point of the port: real motion, not 22 copies of one
    # still frame the way scripts/image_edit_worker.py pads.
    assert context_bounds([40], 200) == (28, 52)


def test_context_bounds_stops_at_both_ends_of_a_short_video():
    assert context_bounds([0, 2], 3) == (0, 2)


def test_context_bounds_widens_forward_when_the_span_sits_at_the_head():
    # An earlier version of this test was named "widens backwards first" and
    # could not fail: swapping the two branches of the widening loop left it
    # green. The order is genuinely UNOBSERVABLE at these constants — +/-12 gives
    # 25 frames, already over the 22 floor, so the loop only runs once an end is
    # clamped, and a clamped end has no room to widen. So pin what IS observable:
    # widening happens on whichever side still has video.
    # LITERAL 21, not MIN_CONTEXT_FRAMES - 1. Writing the expectation in terms
    # of the constant under test made this pass for MIN = 25 as happily as for
    # MIN = 22: the assertion moved with the thing it was meant to pin.
    assert context_bounds([0], 30) == (0, 21)


def test_context_bounds_widens_backward_when_the_span_sits_at_the_tail():
    assert context_bounds([29], 30) == (8, 29)


def test_the_models_frame_floor_is_twenty_two():
    # DiffuEraser's own temporal contract, and the number the still-image path
    # in scripts/image_edit_worker.py borrowed while leaving the method behind.
    assert MIN_CONTEXT_FRAMES == 22


def test_context_bounds_stays_short_rather_than_fabricating_frames():
    # Both ends exhausted and still under the floor: honestly short beats padded
    # with fiction, which is exactly what the still-image path does instead.
    start, end = context_bounds([3], 8)
    assert (start, end) == (0, 7)
    assert end - start + 1 < MIN_CONTEXT_FRAMES


def test_context_bounds_reaches_the_minimum_when_the_video_allows():
    start, end = context_bounds([100], 500)
    assert end - start + 1 >= MIN_CONTEXT_FRAMES


# --- decode_mask ------------------------------------------------------------

def test_decode_mask_reads_the_alpha_channel_of_a_painted_png():
    # The canvas paints white strokes on transparency, so the stroke lives in
    # ALPHA. `maskHasPixels()` on the box scans that same channel at > 8.
    rgba = np.zeros((16, 16, 4), np.uint8)
    rgba[4:8, 4:8] = (255, 255, 255, 255)
    mask = decode_mask(_png_bytes(rgba, "RGBA"), 16, 16)
    assert mask.shape == (16, 16)
    assert mask[5, 5] == 255
    assert mask[0, 0] == 0


def test_decode_mask_reads_a_flattened_white_on_black_png():
    grey = np.zeros((16, 16), np.uint8)
    grey[4:8, 4:8] = 255
    mask = decode_mask(_png_bytes(grey, "L"), 16, 16)
    assert mask[5, 5] == 255 and mask[0, 0] == 0


def test_decode_mask_resizes_a_canvas_that_does_not_match_the_frame():
    grey = np.zeros((8, 8), np.uint8)
    grey[2:6, 2:6] = 255
    mask = decode_mask(_png_bytes(grey, "L"), 16, 16)
    assert mask.shape == (16, 16)


def test_decode_mask_refuses_bytes_that_are_not_an_image():
    with pytest.raises(ValueError):
        decode_mask(b"not a png at all", 16, 16)


def test_decode_mask_thresholds_at_eight():
    # 8 is out, 9 is in — the same threshold the canvas and the production
    # still-image path both use.
    faint = np.zeros((4, 4), np.uint8)
    faint[0, 0] = 8
    faint[1, 1] = 9
    mask = decode_mask(_png_bytes(faint, "L"), 4, 4)
    assert mask[0, 0] == 0
    assert mask[1, 1] == 255


# --- compose_frame ----------------------------------------------------------

def test_compose_frame_leaves_pixels_far_from_the_mask_untouched():
    original = np.full((64, 64, 3), 10, np.uint8)
    repaired = np.full((64, 64, 3), 200, np.uint8)
    out = compose_frame(original, repaired, _mask(64, 64, (30, 34, 30, 34)),
                        (0, 0, 64, 64))
    assert out[0, 0].tolist() == [10, 10, 10]
    assert out[32, 32, 0] >= 195


def test_compose_frame_feathers_the_mask_edge():
    # Long dilates 3x3 then blurs sigma 0.8, so the boundary is NOT a hard cut.
    # This is precisely why this path must not repeat the "outside-mask pixels
    # are byte-identical to input" promise /tools/image-edit makes.
    original = np.zeros((64, 64, 3), np.uint8)
    repaired = np.full((64, 64, 3), 255, np.uint8)
    out = compose_frame(original, repaired, _mask(64, 64, (28, 36, 28, 36)),
                        (0, 0, 64, 64))
    edge = int(out[27, 32, 0])
    assert 0 < edge < 255


def test_compose_frame_resizes_a_crop_that_came_back_at_process_size():
    # The worker returns the crop at process_size, which is smaller than the
    # crop itself whenever the crop exceeded 960x540.
    original = np.full((64, 64, 3), 10, np.uint8)
    small = np.full((16, 16, 3), 200, np.uint8)
    out = compose_frame(original, small, _mask(64, 64, (10, 40, 10, 40)),
                        (8, 8, 40, 40))
    assert out.shape == (64, 64, 3)
    assert out[0, 0].tolist() == [10, 10, 10]
