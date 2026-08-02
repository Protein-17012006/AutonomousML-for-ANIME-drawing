"""gap must survive the wire and a resume, or a reopened session cannot compare
its own pairs."""
from inbetween_copilot.pipeline.models import PairResult
from service.sessions.schemas import PairEvent


def test_pair_event_carries_gap():
    pair = PairResult(0, "filled", "rife", ["a", "m", "b"], None, 0, gap=0.0123)
    assert PairEvent.from_pair(pair).gap == 0.0123


def test_pair_event_gap_is_optional_for_older_events():
    pair = PairResult(0, "filled", "rife", ["a", "m", "b"], None, 0)
    assert PairEvent.from_pair(pair).gap is None
