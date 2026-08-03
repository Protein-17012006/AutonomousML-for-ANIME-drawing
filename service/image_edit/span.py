"""Long's DiffuEraser span-repair maths, ported from
`scripts/run_diffueraser_repair.py` on the 5090 box.

Pure: numpy + cv2 only. No I/O, no FastAPI, no session state — so every rule here
is checkable outside a running service.

Why this module exists at all. `scripts/image_edit_worker.py` repairs a STILL by
writing the same frame 22 times, encoding that as a motionless 4 fps video, and
extracting the middle frame. It borrowed the 22 from `MIN_CONTEXT_FRAMES` below
and left the method behind: it pays for 22 frames of diffusion to obtain one, and
hands a VIDEO inpainting model exactly zero motion. These functions exist so the
session path can give it real neighbouring frames instead.

Every constant is Long's. Changing one silently changes what the model is asked
to reconstruct, which is why each has a test that pins the number.
"""
from __future__ import annotations

import cv2
import numpy as np

# Bounds on the region actually pushed through the model.
MAX_PROCESS_WIDTH = 960
MAX_PROCESS_HEIGHT = 540

# DiffuEraser refuses outright below this: `read_video` raises "The resolution
# of the uploaded video must be larger than 256x256". The still-image path never
# met it because it sends the WHOLE frame; the span path sends a CROP, so a small
# painted region -- a hand, a face -- produced a crop the model rejected and the
# artist was told the worker was unavailable. Found on the box, 2026-08-02; every
# unit test had mocked the worker and so could not see it. 264 is the first
# multiple of 8 above the model's limit.
MIN_MODEL_SIDE = 264

# Real neighbouring frames taken on each side of the painted span, and the
# model's own floor on how many frames it needs to work at all.
CONTEXT_FRAMES = 12
MIN_CONTEXT_FRAMES = 22

# What the MODEL demands, which is NOT the same number: DiffuEraser raises "the
# number of frames of video, mask, and priori is at least greater than 22", i.e.
# it needs 23. Long's widening floor above stops AT 22, so a span it considers
# complete can still be one frame short of acceptable. Kept as its own constant
# because it belongs to the model, not to his maths. Found on the box 2026-08-02:
# a short cut came back as a 503 the artist would read as "the worker is down".
MIN_MODEL_FRAMES = MIN_CONTEXT_FRAMES + 1

# Caps carried over from the Studio's `start_repair`.
MAX_REFINEMENT_PASSES = 20
MAX_REPAIR_FRAMES = 480
MAX_REPAIR_SPAN = 960

# A painted stroke counts from alpha 9 upward. The canvas, the still-image
# worker and this module must agree, or a stroke that looked painted is dropped.
MASK_THRESHOLD = 8

# The diffusion VAE downsamples by this factor; crops snap to it.
GRID = 8


def decode_mask(raw: bytes, width: int, height: int) -> np.ndarray:
    """One painted PNG -> a 0/255 uint8 mask of shape (height, width).

    Both mask encodings in use are accepted: the canvas paints white strokes on
    transparency (stroke lives in ALPHA), while a flattened export carries it in
    luminance. Nearest-neighbour on resize, because a mask must not acquire
    intermediate values on its way to a threshold.
    """
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("could not read mask")
    if image.shape[:2] != (height, width):
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_NEAREST)
    if image.ndim == 2:
        mask = image
    elif image.shape[2] == 4:
        mask = image[:, :, 3]
    else:
        mask = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    return np.where(mask > MASK_THRESHOLD, 255, 0).astype(np.uint8)


def aligned_crop(mask_union: np.ndarray, width: int, height: int) -> tuple:
    """The region sent to the model: the mask's bounding box, padded, snapped
    OUTWARD to the grid, clamped to the frame. Returns (x0, y0, x1, y1).

    Padding is `max(96, 30% of the longer side)` — a floor so a tiny stroke still
    gets context, and a proportion so a large repair is not starved of it.
    """
    points = cv2.findNonZero(mask_union)
    if points is None:
        raise ValueError("the submitted masks are empty")
    x, y, box_width, box_height = cv2.boundingRect(points)
    padding = max(96, round(max(box_width, box_height) * 0.3))
    x0 = max(0, x - padding)
    y0 = max(0, y - padding)
    x1 = min(width, x + box_width + padding)
    y1 = min(height, y + box_height + padding)
    x0 = max(0, (x0 // GRID) * GRID)
    y0 = max(0, (y0 // GRID) * GRID)
    x1 = min(width, ((x1 + GRID - 1) // GRID) * GRID)
    y1 = min(height, ((y1 + GRID - 1) // GRID) * GRID)
    return x0, y0, x1, y1


def grow_crop_to_model_minimum(crop, width: int, height: int,
                               minimum: int = MIN_MODEL_SIDE) -> tuple:
    """Widen a crop until the model will accept it, keeping it inside the frame.

    Growing the CROP rather than upscaling it is deliberate: it hands the model
    more real neighbouring pixels instead of a stretched copy of too few. The
    result stays on the 8-px grid and is clamped to the frame, so a frame that
    is itself too small comes back unchanged and is refused upstream with a
    reason rather than reaching the model and 503-ing."""
    x0, y0, x1, y1 = crop
    for low, high, limit, axis in ((x0, x1, width, "x"), (y0, y1, height, "y")):
        span = high - low
        if span >= minimum:
            continue
        want = min(minimum, (limit // 8) * 8 or limit)
        grow = want - span
        low = max(0, low - (grow + 1) // 2)
        high = min(limit, low + want)
        low = max(0, high - want)           # re-anchor when the top edge clamped
        low, high = (low // 8) * 8, min(limit, ((high + 7) // 8) * 8)
        if axis == "x":
            x0, x1 = low, high
        else:
            y0, y1 = low, high
    return x0, y0, x1, y1


def process_size(crop_width: int, crop_height: int) -> tuple:
    """Never upscales; bounds to 960x540; keeps the grid; floors at 64."""
    scale = min(1.0,
                MAX_PROCESS_WIDTH / crop_width,
                MAX_PROCESS_HEIGHT / crop_height)
    width = max(64, int(crop_width * scale) // GRID * GRID)
    height = max(64, int(crop_height * scale) // GRID * GRID)
    return width, height


def context_bounds(target_frames, frame_count: int) -> tuple:
    """The real neighbouring frames the model receives, as (start, end) inclusive.

    Takes +/-CONTEXT_FRAMES around the painted span, then widens BACKWARDS FIRST
    until MIN_CONTEXT_FRAMES is met, and STOPS when the video runs out rather
    than fabricating frames. A span at the very start of a short cut therefore
    gets fewer than the minimum — honestly short beats padded with fiction.
    """
    start = max(0, target_frames[0] - CONTEXT_FRAMES)
    end = min(frame_count - 1, target_frames[-1] + CONTEXT_FRAMES)
    while end - start + 1 < MIN_CONTEXT_FRAMES:
        if start > 0:
            start -= 1
        elif end < frame_count - 1:
            end += 1
        else:
            break
    return start, end


def compose_frame(original: np.ndarray, repaired_crop: np.ndarray,
                  mask: np.ndarray, crop) -> np.ndarray:
    """Blend the repaired crop back through a FEATHERED mask.

    Dilate 3x3 then blur sigma 0.8: a hard cut leaves a visible seam on line art.
    The cost is real and must be stated wherever this path is documented —
    pixels just outside the painted stroke DO change, so this cannot repeat the
    "outside-mask pixels are byte-identical to input" contract that
    `service/image_edit/service.py` makes for the stateless tool.
    """
    x0, y0, x1, y1 = crop
    crop_width = x1 - x0
    crop_height = y1 - y0
    if repaired_crop.shape[1] != crop_width or repaired_crop.shape[0] != crop_height:
        repaired_crop = cv2.resize(repaired_crop, (crop_width, crop_height),
                                   interpolation=cv2.INTER_CUBIC)
    local_mask = cv2.dilate(mask[y0:y1, x0:x1], np.ones((3, 3), np.uint8),
                            iterations=1)
    alpha = (cv2.GaussianBlur(local_mask, (0, 0), 0.8).astype(np.float32) / 255.0)
    alpha = alpha[:, :, None]
    result = original.copy()
    blended = (repaired_crop.astype(np.float32) * alpha
               + original[y0:y1, x0:x1].astype(np.float32) * (1.0 - alpha))
    result[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
    return result


__all__ = [
    "CONTEXT_FRAMES", "GRID", "MASK_THRESHOLD", "MAX_PROCESS_HEIGHT",
    "MAX_PROCESS_WIDTH", "MAX_REFINEMENT_PASSES", "MAX_REPAIR_FRAMES",
    "MAX_REPAIR_SPAN", "MIN_CONTEXT_FRAMES", "aligned_crop", "compose_frame",
    "context_bounds", "decode_mask", "process_size",
]
