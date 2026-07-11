"""PairEvent must carry the correction-loop trace (director demo surface)."""
from inbetween_copilot.generate.correction import CorrectionResult, CorrectionRound
from inbetween_copilot.pipeline.copilot import PairResult
from inbetween_copilot.qa.gate import FrameQA
from service.sessions.schemas import PairEvent


def _pair_with_correction():
    rounds = [
        CorrectionRound("region_refill", None, None, reason="director: localized ghost"),
        CorrectionRound("ask_key", None, None, reason="abstain-after-fix"),
    ]
    corr = CorrectionResult("needs_key", ["f"], rounds, 0, None)
    return PairResult(3, "filled", "rife", ["a", "m", "b"],
                      FrameQA(status="flag", reason="detector"), 0, correction=corr)


def test_pair_event_carries_correction_trace():
    ev = PairEvent.from_pair(_pair_with_correction())
    assert ev.correction == {
        "status": "needs_key",
        "keys_used": 0,
        "rounds": [
            {"action": "region_refill", "reason": "director: localized ghost"},
            {"action": "ask_key", "reason": "abstain-after-fix"},
        ],
    }


def test_pair_event_without_correction_is_none():
    p = PairResult(0, "filled", "rife", ["a", "m", "b"],
                   FrameQA(status="pass", reason=""), 0)
    assert PairEvent.from_pair(p).correction is None
