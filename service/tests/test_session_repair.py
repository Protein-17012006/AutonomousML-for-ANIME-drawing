"""Long's refusals, kept verbatim, plus the rules the cloud adds.

The load-bearing one: the session never holds new pixels under an old verdict,
so repair_pair computes and RETURNS; it must never write into state.
"""
from __future__ import annotations

import base64
import copy
import io

import numpy as np
import pytest
from PIL import Image

from service.core.errors import ImageEditUnavailable
from service.image_edit.session_repair import (
    repair_pair,
    validate_repair_request,
)
from inbetween_copilot.pipeline.models import CopilotResult, PairResult
from inbetween_copilot.qa.models import FrameQA


# Above span.MIN_MODEL_SIDE: DiffuEraser refuses <=256x256, and repair now
# refuses such a session up front rather than 503-ing from the worker.
HEIGHT, WIDTH = 288, 288


def _png_bytes(box=(80, 200, 80, 200)) -> bytes:
    rgba = np.zeros((HEIGHT, WIDTH, 4), np.uint8)
    y0, y1, x0, x1 = box
    rgba[y0:y1, x0:x1] = (255, 255, 255, 255)
    buffer = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def _data_url(raw: bytes | None = None) -> str:
    payload = base64.b64encode(raw if raw is not None else _png_bytes())
    return "data:image/png;base64," + payload.decode("ascii")


PNG = _data_url()
PNG_BYTES = _png_bytes()


def _frame(value: int) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), value, np.uint8)


def _qa(status: str = "pass") -> FrameQA:
    return FrameQA(status=status, reason="stub")


class _Cfg:
    smoothness = 2


def _pair(index: int, action: str, *, values, qa_status="pass",
          artist_verdict=None) -> PairResult:
    return PairResult(
        index=index,
        action=action,
        route="rife" if action != "needs_key" else None,
        frames=[_frame(value) for value in values] if values else None,
        qa=_qa(qa_status) if action != "needs_key" else None,
        keys_requested=0,
        artist_verdict=artist_verdict,
    )


def _chain(count: int) -> list[PairResult]:
    """Pairs 1..count, each sharing its leading key with the previous pair."""
    return [_pair(k, "filled", values=(10 + 20 * (k - 1), 20 + 20 * (k - 1),
                                       30 + 20 * (k - 1)))
            for k in range(1, count + 1)]


@pytest.fixture
def state() -> dict:
    # Pair 0 is gate-refused; pairs 1..12 each carry three frames whose shared
    # boundary key is deduped by the assembler, so pair 1 owns cut frames 0,1,2
    # and pair 2 owns 3,4 -- and the cut is 25 frames, over the model's floor of
    # 23. Pairs 3..12 are there only to clear that floor; shortening them puts
    # every success case back on the short-cut refusal.
    pairs = [_pair(0, "needs_key", values=None), *_chain(12)]
    result = CopilotResult(pairs=pairs, keys_requested_total=1, flagged=[],
                           n_autopass=12)
    return {"result": result, "cfg": _Cfg(), "eng": None}


@pytest.fixture
def short_state() -> dict:
    pairs = [_pair(0, "needs_key", values=None), *_chain(2)]
    result = CopilotResult(pairs=pairs, keys_requested_total=1, flagged=[],
                           n_autopass=2)
    return {"result": result, "cfg": _Cfg(), "eng": None}


def _ok_editor(frames, masks, *, model, seed, refinement_passes):
    return [np.full_like(frame, 200) for frame in frames]


def _qa_ok(frames, pair):
    return _qa("pass")


def _qa_flags(frames, pair):
    return _qa("flag")


def _qa_raises(frames, pair):
    raise RuntimeError("CSQ re-run failed")


# --- validation ------------------------------------------------------------

def test_rejects_an_empty_mask_list(state):
    with pytest.raises(ValueError, match="at least one"):
        validate_repair_request(state, 1, [], 1)


def test_rejects_refinement_passes_out_of_range(state):
    with pytest.raises(ValueError, match="refinement"):
        validate_repair_request(state, 1, [{"frame": 1, "png": PNG}], 21)
    with pytest.raises(ValueError, match="refinement"):
        validate_repair_request(state, 1, [{"frame": 1, "png": PNG}], 0)


def test_rejects_a_frame_submitted_twice(state):
    with pytest.raises(ValueError, match="twice"):
        validate_repair_request(
            state, 1, [{"frame": 1, "png": PNG}, {"frame": 1, "png": PNG}], 1)


def test_rejects_a_pair_outside_the_result(state):
    with pytest.raises(ValueError, match="outside"):
        validate_repair_request(state, 99, [{"frame": 1, "png": PNG}], 1)


def test_rejects_a_needs_key_pair(state):
    # A gate-refused pair was never filled: there is no generated frame to
    # repair, and offering one repeats the missing-artefact defect.
    with pytest.raises(ValueError, match="no generated frame"):
        validate_repair_request(state, 0, [{"frame": 1, "png": PNG}], 1)


def test_rejects_a_frame_outside_the_reconstructed_cut(state):
    with pytest.raises(ValueError, match="outside"):
        validate_repair_request(state, 1, [{"frame": 9999, "png": PNG}], 1)


def test_rejects_the_key_a_pair_shares_with_its_predecessor(state):
    # Pair 2's position 0 is the key it shares with pair 1; the assembler drops
    # it, so on screen that frame belongs to pair 1. The route is pair-scoped
    # and must not write another pair's frame.
    with pytest.raises(ValueError, match="pair 2"):
        validate_repair_request(state, 2, [{"frame": 0, "png": PNG}], 1)


def test_translates_pair_positions_into_cut_frames(state):
    # The wire is pair-local; context_bounds needs cut coordinates. Pair 2's
    # positions 1 and 2 are cut frames 3 and 4, NOT 1 and 2 -- so a translation
    # that merely passed the number through would go red here.
    decoded = validate_repair_request(
        state, 2, [{"frame": 1, "png": PNG}, {"frame": 2, "png": PNG}], 1)
    assert [cut_frame for cut_frame, _ in decoded] == [3, 4]


def test_rejects_a_mask_that_is_not_a_png(state):
    with pytest.raises(ValueError, match="PNG"):
        validate_repair_request(
            state, 1, [{"frame": 1, "png": "data:image/png;base64,zzzz"}], 1)


def test_rejects_a_payload_that_is_not_a_data_url(state):
    with pytest.raises(ValueError, match="PNG"):
        validate_repair_request(
            state, 1, [{"frame": 1, "png": base64.b64encode(PNG_BYTES).decode()}], 1)


def test_rejects_a_payload_whose_bytes_are_not_a_png(state):
    not_png = base64.b64encode(b"GIF89a" + b"\x00" * 64).decode("ascii")
    with pytest.raises(ValueError, match="PNG"):
        validate_repair_request(
            state, 1, [{"frame": 1, "png": "data:image/png;base64," + not_png}], 1)


def test_rejects_a_cut_too_short_for_the_model(short_state):
    # DiffuEraser needs MORE than 22 frames. context_bounds deliberately stays
    # short rather than fabricating any, so a 5-frame cut can never produce an
    # acceptable span -- and before this guard it came back as a 503 the artist
    # would read as "the worker is down". Found on the box, not by this suite.
    with pytest.raises(ValueError, match="needs at least 23"):
        validate_repair_request(short_state, 1, [{"frame": 1, "png": PNG}], 1)


def test_rejects_a_frame_smaller_than_the_model_accepts():
    # The model refuses <=256x256 outright; say so instead of 503-ing.
    small = _pair(0, "filled", values=(10, 20, 30))
    small.frames = [np.full((64, 64, 3), v, np.uint8) for v in (10, 20, 30)]
    tiny = {
        "result": CopilotResult(pairs=[small], keys_requested_total=0,
                                flagged=[], n_autopass=1),
        "cfg": _Cfg(), "eng": None,
    }
    with pytest.raises(ValueError, match="at least 264x264"):
        validate_repair_request(tiny, 0, [{"frame": 1, "png": PNG}], 1)


def test_rejects_smoothness_above_the_supported_ceiling(state):
    # Above x2 the cut contains SYNTHESISED frames with no home in pair.frames,
    # so a repair would be written to the wrong frame rather than refused.
    state["cfg"].smoothness = 4
    with pytest.raises(ValueError, match="smoothness"):
        validate_repair_request(state, 1, [{"frame": 1, "png": PNG}], 1)


def test_accepts_painted_frames_and_returns_them_sorted(state):
    # Three frames, submitted 2-0-1: with two, `reversed` and `sorted` agree and
    # the ordering is not actually pinned.
    decoded = validate_repair_request(
        state, 1,
        [{"frame": 2, "png": PNG}, {"frame": 0, "png": PNG},
         {"frame": 1, "png": PNG}],
        1,
    )
    assert [frame for frame, _ in decoded] == [0, 1, 2]
    assert all(raw.startswith(b"\x89PNG\r\n\x1a\n") for _, raw in decoded)


# --- orchestration ---------------------------------------------------------

def _recon(state):
    from service.media.artifacts import assemble_frames_with_provenance
    return assemble_frames_with_provenance(state["result"], factor=2)


def _snapshot(result) -> list[tuple]:
    """Everything a repair could touch, as comparable primitives.

    `==` on PairResult is ambiguous once frames hold numpy arrays, so it would
    raise rather than compare -- and a test that raises where it means to assert
    is testing nothing.
    """
    return [
        (
            pair.index,
            str(pair.action),
            pair.artist_verdict,
            getattr(pair.qa, "status", None),
            tuple(np.asarray(frame).tobytes() for frame in (pair.frames or ())),
        )
        for pair in result.pairs
    ]


def test_repair_pair_does_not_mutate_state_when_qa_raises(state):
    before = _snapshot(state["result"])
    with pytest.raises(RuntimeError):
        repair_pair(state, 1, [(1, PNG_BYTES)], span_editor=_ok_editor,
                    qa_fn=_qa_raises, recon_fn=_recon)
    assert _snapshot(state["result"]) == before


def test_repair_pair_does_not_mutate_state_when_the_worker_is_unavailable(state):
    before = _snapshot(state["result"])

    def down(*args, **kwargs):
        raise ImageEditUnavailable("worker down")

    with pytest.raises(ImageEditUnavailable):
        repair_pair(state, 1, [(1, PNG_BYTES)], span_editor=down,
                    qa_fn=_qa_ok, recon_fn=_recon)
    assert _snapshot(state["result"]) == before


def test_repair_pair_leaves_the_session_untouched_on_success_too(state):
    # The success path is the one that MATTERS: a repair that quietly wrote the
    # new frames in would defeat the whole atomic-publish rule while every
    # failure-path test above stayed green.
    before = _snapshot(state["result"])
    repair_pair(state, 1, [(1, PNG_BYTES)], span_editor=_ok_editor,
                qa_fn=_qa_flags, recon_fn=_recon)
    assert _snapshot(state["result"]) == before


def test_repair_pair_returns_the_re_run_verdict_not_the_old_one(state):
    out = repair_pair(state, 1, [(1, PNG_BYTES)], span_editor=_ok_editor,
                      qa_fn=_qa_flags, recon_fn=_recon)
    assert out["qa"].status == "flag"
    assert out["pair_index"] == 1
    # still unpublished: the caller owns the commit
    assert state["result"].pairs[1].qa.status == "pass"


def test_repair_pair_changes_only_the_painted_frame_of_that_pair(state):
    out = repair_pair(state, 1, [(1, PNG_BYTES)], span_editor=_ok_editor,
                      qa_fn=_qa_ok, recon_fn=_recon)
    frames = out["frames"]
    assert len(frames) == 3
    # cut frame 1 is pair 1's position 1
    assert not np.array_equal(frames[1], _frame(20))
    assert np.array_equal(frames[0], _frame(10))
    assert np.array_equal(frames[2], _frame(30))


def test_repair_pair_leaves_pixels_far_from_the_mask_untouched(state):
    out = repair_pair(state, 1, [(1, PNG_BYTES)], span_editor=_ok_editor,
                      qa_fn=_qa_ok, recon_fn=_recon)
    repaired = out["frames"][1]
    # The mask covers rows/cols 80..200. A corner pixel is outside it, so even
    # though the crop now grows to the model's 264 minimum it must keep its
    # original value: the crop decides what the MODEL sees, the mask decides
    # what is written back.
    assert repaired[0, 0].tolist() == [20, 20, 20]
    assert repaired[140, 140].tolist() != [20, 20, 20]


def test_repair_pair_hands_the_editor_real_neighbouring_frames(state):
    seen = {}

    def recording_editor(frames, masks, *, model, seed, refinement_passes):
        seen.update(frames=frames, masks=masks, seed=seed,
                    passes=refinement_passes)
        return [np.full_like(frame, 200) for frame in frames]

    repair_pair(state, 1, [(1, PNG_BYTES)], span_editor=recording_editor,
                qa_fn=_qa_ok, recon_fn=_recon, seed=77, refinement_passes=5)

    # The whole point of the span path: REAL neighbouring frames. Painting cut
    # frame 1 of a 25-frame cut widens forward to MIN_CONTEXT_FRAMES, so the
    # model gets 22 genuine frames rather than 22 copies of one still.
    assert len(seen["frames"]) == 22
    assert len({frame.tobytes() for frame in seen["frames"]}) > 1
    assert list(seen["masks"]) == [1]
    assert seen["seed"] == 77 and seen["passes"] == 5


def test_repair_pair_writes_to_the_position_the_boundary_dedup_implies(state):
    # Pair 2's first frame is the key it SHARES with pair 1, so the assembler
    # drops it: cut frame 3 is pair 2's frames[1], not frames[0]. Off by one
    # here and the repair lands on the artist's own key.
    out = repair_pair(state, 2, [(3, PNG_BYTES)], span_editor=_ok_editor,
                      qa_fn=_qa_ok, recon_fn=_recon)
    frames = out["frames"]
    assert np.array_equal(frames[0], _frame(30))
    assert not np.array_equal(frames[1], _frame(40))
    assert np.array_equal(frames[2], _frame(50))


@pytest.fixture
def long_state() -> dict:
    # A cut long enough that context_bounds cannot start at 0: three pairs of
    # twelve frames each, sharing boundary keys, gives a 34-frame cut.
    pairs = []
    value = 0
    for index in range(3):
        values = [value + step for step in range(12)]
        pairs.append(_pair(index, "filled", values=values))
        value = values[-1]
    result = CopilotResult(pairs=pairs, keys_requested_total=0, flagged=[],
                           n_autopass=3)
    return {"result": result, "cfg": _Cfg(), "eng": None}


def test_repair_pair_keys_masks_in_span_coordinates(long_state):
    seen = {}

    def recording_editor(frames, masks, *, model, seed, refinement_passes):
        seen.update(frames=frames, masks=masks)
        return [np.full_like(frame, 200) for frame in frames]

    # Cut frame 20 with +/-12 context gives a span starting at 8, so the span
    # offset (12) and the cut index (20) genuinely differ. The worker indexes
    # into the list it was handed and knows nothing of cut coordinates.
    repair_pair(long_state, 1, [(20, PNG_BYTES)], span_editor=recording_editor,
                qa_fn=_qa_ok, recon_fn=_recon)
    assert list(seen["masks"]) == [12]
    assert len(seen["frames"]) == 25


def test_repair_pair_runs_qa_on_the_repaired_frames_not_the_old_ones(state):
    seen = {}

    def recording_qa(frames, pair):
        seen["frames"] = [np.asarray(frame).copy() for frame in frames]
        return _qa("pass")

    out = repair_pair(state, 1, [(1, PNG_BYTES)], span_editor=_ok_editor,
                      qa_fn=recording_qa, recon_fn=_recon)
    # Judging the old pixels would certify a frame nobody is going to see.
    assert not np.array_equal(seen["frames"][1], _frame(20))
    assert np.array_equal(seen["frames"][1], out["frames"][1])
