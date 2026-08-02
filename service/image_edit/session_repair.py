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

from inbetween_copilot.pipeline.copilot import _qa_for
from inbetween_copilot.qa.window import windows_for_run

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

    Masks arrive keyed by POSITION WITHIN THE PAIR — ``{"frame": 1}`` is that
    pair's mid — and leave in reconstructed-cut coordinates, which is what
    ``context_bounds`` needs. Keeping the public payload pair-local is what
    makes "a frame belonging to another pair" unrepresentable rather than
    merely refused: the route is pair-scoped, so its coordinates should be too.

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

    # position within pair.frames -> index into the reconstructed cut. A
    # position the assembler deduped away (a pair's shared leading key) is
    # absent here and is refused below: it is another pair's frame on screen.
    # No redundant "owns nothing" guard: it would raise the same sentence as
    # the needs_key check above, making the two indistinguishable to a test.
    cut_index_of = {
        position: cut_index
        for cut_index, position in _pair_frame_positions(state, index).items()
    }
    seen: set[int] = set()
    decoded: list[tuple[int, bytes]] = []
    for entry in masks:
        position = entry.get("frame") if isinstance(entry, dict) else None
        if not isinstance(position, int) or isinstance(position, bool):
            raise ValueError("each mask must name an integer frame")
        if position in seen:
            raise ValueError(f"frame {position} was submitted twice")
        seen.add(position)
        if position not in cut_index_of:
            raise ValueError(
                f"frame {position} is outside pair {index}'s generated frames"
            )
        decoded.append((cut_index_of[position],
                        _decode_data_url(entry.get("png"))))

    cut_frames = [cut_index for cut_index, _ in decoded]
    span = max(cut_frames) - min(cut_frames) + 1
    if span > MAX_REPAIR_SPAN:
        raise ValueError(
            f"the painted frames span {span} frames, over the {MAX_REPAIR_SPAN} limit"
        )
    return sorted(decoded)


def qa_blast_radius(pairs, repaired_index: int, *, qa_window: bool) -> list[int]:
    """Which pairs' verdicts a repair of ``repaired_index`` invalidates.

    With ``qa_window`` off, QA judges a pair's own triplet and only that pair is
    affected. With it on — production — QA judges a 16-frame CENTERED window
    built from the whole contiguous run (``qa/window.py``), so repairing one pair
    changes the input to its neighbours' verdicts too. Recomputing only the
    repaired pair would leave those neighbours certified against pixels that no
    longer exist: the same defect this feature forbids, displaced one pair
    sideways. At W=16 a window spans roughly the whole run, so the contiguous
    run is the honest unit.
    """
    if not qa_window:
        return [repaired_index]
    fillable = sorted(
        pair.index for pair in pairs
        if str(pair.action) in ("filled", "generated") and pair.frames
    )
    run = [repaired_index]
    for index in fillable:
        if index < repaired_index and all(
            neighbour in fillable for neighbour in range(index, repaired_index)
        ):
            run.append(index)
        elif index > repaired_index and all(
            neighbour in fillable for neighbour in range(repaired_index + 1, index + 1)
        ):
            run.append(index)
    return sorted(set(run))


def rerun_qa(pairs, indices, *, qa_fn, softness_fn, qa3_fn, tau_soft,
             qa_window: bool) -> dict:
    """Recompute the calibrated verdict for ``indices`` from the current frames.

    Delegates to the pipeline's own ``_qa_for`` rather than restating the CSQ
    deployment-swap contract (3-state when wired, binary OR-union otherwise) —
    a second copy of that rule would drift away from the one the run used.
    """
    by_index = {pair.index: pair for pair in pairs}
    windows = {}
    if qa_window:
        windows = windows_for_run([
            (pair.index, pair.frames) for pair in pairs
            if str(pair.action) in ("filled", "generated") and pair.frames
        ])
    verdicts = {}
    for index in indices:
        pair = by_index[index]
        qa_input = windows.get(index, pair.frames) if qa_window else pair.frames
        verdicts[index] = _qa_for(qa_input, qa_fn, softness_fn, qa3_fn, tau_soft)
    return verdicts


def assembled_cut(state: dict):
    """The reconstructed cut and its per-frame provenance, as the renderer builds it."""
    from service.media.artifacts import assemble_frames_with_provenance

    return assemble_frames_with_provenance(
        state["result"],
        factor=getattr(state["cfg"], "smoothness", SUPPORTED_SMOOTHNESS),
        mid_engine=getattr(state.get("eng"), "rife_engine", None),
    )


def _cut(state: dict, recon_fn):
    frames, provenance = (recon_fn or assembled_cut)(state)
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
                recon_fn=None, model: str = "diffueraser", seed: int = 2026,
                refinement_passes: int = 1) -> dict:
    """:func:`repair_frames` plus the pair's own re-run verdict. Pure.

    QA runs on the repaired frames before anything is returned, so a caller that
    publishes this dict can never publish pixels the verdict did not see.
    """
    frames = repair_frames(
        state, index, decoded, span_editor=span_editor, recon_fn=recon_fn,
        model=model, seed=seed, refinement_passes=refinement_passes)
    return {
        "frames": frames,
        "qa": qa_fn(frames, _pairs_by_index(state)[index]),
        "pair_index": index,
    }


def repair_frames(state: dict, index: int, decoded, *, span_editor,
                  recon_fn=None, model: str = "diffueraser", seed: int = 2026,
                  refinement_passes: int = 1) -> list:
    """One pair's frames with the painted regions repaired. ``state`` is not touched.

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

    return new_frames
