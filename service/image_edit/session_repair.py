"""In-session frame repair: validate one artist request, then compute it.

Two responsibilities, deliberately split from the commit:

* :func:`validate_repair_request` carries Long's refusals from
  ``run_diffueraser_repair.py`` plus the ones the cloud adds, and it runs
  BEFORE any GPU work.
* :func:`repair_pair` computes the repaired frames and the re-run QA verdict and
  **returns** them. It never writes into ``state``.

That split is the load-bearing rule of this feature: the session must never hold
new pixels under an old verdict, so the caller publishes frames, verdict and the
cleared ``artist_verdict`` in one revision, or publishes nothing.
"""
from __future__ import annotations

import base64
import binascii

import cv2
import numpy as np

from service.image_edit.span import (
    MAX_REFINEMENT_PASSES,
    MAX_REPAIR_FRAMES,
    MAX_REPAIR_SPAN,
    aligned_crop,
    compose_frame,
    context_bounds,
    decode_mask,
    process_size,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_MASK_BYTES = 8 * 1024 * 1024
# Above x2 the reconstructed cut carries frames synthesised by expand_pair that
# have no position in PairResult.frames, so a repair could not be written back
# to the frame the artist painted. x2 is the shipped ceiling
# (Smoothness Control, ADR); refusing here refuses nothing reachable today.
SUPPORTED_SMOOTHNESS = 2


def _pairs_by_index(state: dict) -> dict:
    return {pair.index: pair for pair in state["result"].pairs}


def _decode_data_url(payload) -> bytes:
    if not isinstance(payload, str) or "base64," not in payload:
        raise ValueError("each mask must be a base64 PNG data URL")
    try:
        raw = base64.b64decode(payload.split("base64,", 1)[1], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("each mask must be a base64 PNG data URL") from exc
    if not raw.startswith(PNG_MAGIC):
        raise ValueError("each mask must be a base64 PNG data URL")
    if len(raw) > MAX_MASK_BYTES:
        raise ValueError("a mask PNG exceeds the 8 MB limit")
    return raw


def validate_repair_request(state: dict, index: int, masks, refinement_passes: int):
    """Return ``[(cut_frame, png_bytes), ...]`` sorted by frame, or raise.

    Every refusal states its reason, because a route that answers 422 without
    naming which rule fired cannot be diagnosed and cannot be tested for.
    """
    if not masks:
        raise ValueError("paint at least one frame before submitting a repair")
    if not isinstance(refinement_passes, int) or not (
        1 <= refinement_passes <= MAX_REFINEMENT_PASSES
    ):
        raise ValueError(
            f"refinement passes must be between 1 and {MAX_REFINEMENT_PASSES}"
        )
    if len(masks) > MAX_REPAIR_FRAMES:
        raise ValueError(f"a repair may cover at most {MAX_REPAIR_FRAMES} frames")

    smoothness = getattr(state["cfg"], "smoothness", SUPPORTED_SMOOTHNESS)
    if smoothness != SUPPORTED_SMOOTHNESS:
        raise ValueError(
            f"in-session repair supports smoothness x{SUPPORTED_SMOOTHNESS} only; "
            f"this session rendered at x{smoothness}"
        )

    pair = _pairs_by_index(state).get(index)
    if pair is None:
        raise ValueError(f"pair {index} is outside this result")
    if str(pair.action) == "needs_key" or not pair.frames:
        raise ValueError(f"pair {index} has no generated frame to repair")

    # No redundant "owns no cut frames" guard here: it would raise the same
    # sentence as the check above, making the two indistinguishable to a test.
    owned = _pair_frame_positions(state, index)
    seen: set[int] = set()
    decoded: list[tuple[int, bytes]] = []
    for entry in masks:
        frame = entry.get("frame") if isinstance(entry, dict) else None
        if not isinstance(frame, int) or isinstance(frame, bool):
            raise ValueError("each mask must name an integer frame")
        if frame in seen:
            raise ValueError(f"frame {frame} was submitted twice")
        seen.add(frame)
        if frame not in owned:
            raise ValueError(
                f"frame {frame} is outside pair {index}'s generated frames"
            )
        decoded.append((frame, _decode_data_url(entry.get("png"))))

    span = max(seen) - min(seen) + 1
    if span > MAX_REPAIR_SPAN:
        raise ValueError(
            f"the painted frames span {span} frames, over the {MAX_REPAIR_SPAN} limit"
        )
    return sorted(decoded)


def _cut(state: dict, recon_fn):
    frames, provenance = recon_fn(state)
    if not frames:
        raise ValueError("this session has no reconstructed frames to repair")
    return frames, provenance


def _pair_frame_positions(state: dict, index: int, recon_fn=None) -> dict:
    """Map cut-frame index -> position inside that pair's ``frames`` list."""
    if recon_fn is None:
        from service.media.artifacts import assemble_frames_with_provenance

        def recon_fn(current):
            return assemble_frames_with_provenance(
                current["result"],
                factor=getattr(current["cfg"], "smoothness", 2),
                mid_engine=getattr(current.get("eng"), "rife_engine", None),
            )

    _frames, provenance = recon_fn(state)
    return {
        cut_index: position
        for cut_index, (pair_index, position) in enumerate(provenance)
        if pair_index == index
    }


def repair_pair(state: dict, index: int, decoded, *, span_editor, qa_fn,
                recon_fn, model: str = "diffueraser", seed: int = 2026,
                refinement_passes: int = 1) -> dict:
    """Repair one pair's painted frames and re-run QA. ``state`` is not touched.

    Temporal context is drawn from the reconstructed cut rather than the pair,
    because a pair exposes only its own handful of frames while the cut carries
    every frame in order — which is what ``context_bounds`` needs to find real
    motion around the frame being repaired.
    """
    frames, provenance = _cut(state, recon_fn)
    owned = {
        cut_index: position
        for cut_index, (pair_index, position) in enumerate(provenance)
        if pair_index == index
    }
    painted = [frame for frame, _ in decoded]
    height, width = np.asarray(frames[painted[0]]).shape[:2]

    start, end = context_bounds(painted, len(frames))
    span = [np.asarray(frame, dtype=np.uint8) for frame in frames[start:end + 1]]

    masks = {
        cut_index: decode_mask(raw, width, height) for cut_index, raw in decoded
    }
    union = np.zeros((height, width), np.uint8)
    for mask in masks.values():
        union = np.maximum(union, mask)
    crop = aligned_crop(union, width, height)
    x0, y0, x1, y1 = crop
    send_width, send_height = process_size(x1 - x0, y1 - y0)

    def _resized(image, interpolation):
        window = image[y0:y1, x0:x1]
        if (send_width, send_height) == (x1 - x0, y1 - y0):
            return window
        return cv2.resize(window, (send_width, send_height),
                          interpolation=interpolation)

    repaired_span = span_editor(
        [_resized(frame, cv2.INTER_AREA) for frame in span],
        {
            cut_index - start: _resized(mask, cv2.INTER_NEAREST)
            for cut_index, mask in masks.items()
        },
        model=model,
        seed=seed,
        refinement_passes=refinement_passes,
    )

    pair = _pairs_by_index(state)[index]
    new_frames = [np.asarray(frame, dtype=np.uint8).copy()
                  for frame in pair.frames]
    for cut_index, mask in masks.items():
        new_frames[owned[cut_index]] = compose_frame(
            np.asarray(frames[cut_index], dtype=np.uint8),
            np.asarray(repaired_span[cut_index - start], dtype=np.uint8),
            mask,
            crop,
        )

    # QA runs on the repaired frames BEFORE anything is returned. If it raises,
    # the caller has nothing to publish and the session is untouched.
    return {
        "frames": new_frames,
        "qa": qa_fn(new_frames, pair),
        "pair_index": index,
    }
