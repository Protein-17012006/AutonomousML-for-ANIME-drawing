"""`escalate_engine` destroyed the in-between it was asked to improve.

Measured on a live GIMM session (2026-08-03): pairs 2, 4, 5 and 6 came out with
the middle frame BYTE-IDENTICAL to key A (gap 0.00000), and CSQ correctly scored
them p=0.92 — 8% clean. Pair 3, which took `region_refill` instead, kept a real
in-between. The correlation was exact.

Cause: no generative stage [C] is in production, so `anisora_gen` is an identity
stub, and `escalate_fn` calls it as `anisora_gen(a, a, b)` — passing key A as the
middle. `[a, a, b]` comes back and `_escalate` discards the original frames.

So "escalate to the stronger generator" silently replaced a real interpolation
with a frozen hold whenever no stronger generator existed. `decide_fixed` picks
escalate on every round 1, so this reached ANY flagged pair; RIFE simply flagged
rarely enough to hide it.
"""
import numpy as np

from inbetween_copilot.generate.commands import CorrectionCommands
from inbetween_copilot.generate.models import CorrectionAction


def _frames():
    a = np.zeros((8, 8, 3), np.uint8)
    mid = np.full((8, 8, 3), 128, np.uint8)      # a real, distinct in-between
    b = np.full((8, 8, 3), 255, np.uint8)
    return [a, mid, b], a, b


def _commands(escalate_fn):
    return CorrectionCommands(
        refill_fn=lambda frames, a, b, region: list(frames),
        escalate_fn=escalate_fn,
        askkey_fn=lambda a, b: None,
        split_fill_fn=lambda a, m, b: [a, m, b],
    )


def test_an_unavailable_generator_leaves_the_interpolation_alone():
    frames, a, b = _frames()
    out = _commands(lambda a_, b_: None).execute(
        CorrectionAction("escalate_engine", None, "", "r"), frames, a, b)
    assert [f.tolist() for f in out.frames] == [f.tolist() for f in frames]


def test_the_middle_never_becomes_a_copy_of_a_key_when_escalation_is_a_noop():
    """The exact live defect: mid ≡ key A."""
    frames, a, b = _frames()
    out = _commands(lambda a_, b_: None).execute(
        CorrectionAction("escalate_engine", None, "", "r"), frames, a, b)
    assert not np.array_equal(out.frames[1], a)


def test_a_real_generator_is_still_adopted():
    frames, a, b = _frames()
    better = [a, np.full((8, 8, 3), 200, np.uint8), b]
    out = _commands(lambda a_, b_: better).execute(
        CorrectionAction("escalate_engine", None, "", "r"), frames, a, b)
    assert np.array_equal(out.frames[1], better[1])
