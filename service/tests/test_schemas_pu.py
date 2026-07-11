"""P2+D contract: PairEvent's confidence numbers ride TYPED FrameQA fields;
the reason-string regex is legacy fallback only (a reformat of the note must
no longer kill the UI confidence meter)."""
from types import SimpleNamespace

from inbetween_copilot.pipeline.states import QAStatus
from inbetween_copilot.qa.gate import FrameQA, frame_qa_from_verdict
from service.sessions.schemas import PairEvent


def _pair(qa):
    return SimpleNamespace(index=0, action="filled", route="rife",
                           keys_requested=0, qa=qa, correction=None, triage=None)


def test_typed_pu_wins_even_with_mangled_note():
    qa = FrameQA(status=QAStatus.FLAG, reason="TOTALLY REWORDED NOTE (no numbers)",
                 p_error=0.83, u=0.12)
    ev = PairEvent.from_pair(_pair(qa))
    assert ev.verdict_prob == 0.83 and ev.uncertainty == 0.12


def test_legacy_note_regex_still_parses_old_pairs():
    qa = FrameQA(status=QAStatus.FLAG, reason="csq:flag p=0.70 u=0.30")  # no typed fields
    ev = PairEvent.from_pair(_pair(qa))
    assert ev.verdict_prob == 0.70 and ev.uncertainty == 0.30


def test_frame_qa_from_verdict_sets_typed_fields_and_same_note():
    v = SimpleNamespace(decision=QAStatus.ABSTAIN, p_error=0.5, u=0.4)
    qa = frame_qa_from_verdict(v)
    assert qa.p_error == 0.5 and qa.u == 0.4 and qa.status == "abstain"
    assert qa.reason == "csq:abstain p=0.50 u=0.40"   # byte-identical note format
