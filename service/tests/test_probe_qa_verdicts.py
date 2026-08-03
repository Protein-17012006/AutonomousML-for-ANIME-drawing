"""The probe's conclusion must be readable off the rows, not asserted by hand.

Spec 6 exists because "zero flags and zero abstains" was recorded without anyone
being able to say WHICH guard failed to fire. A row that a guard should have
downgraded, and did not, is the finding — so the probe has to name it.
"""
from scripts.probe_qa_verdicts import classify_rows


def test_a_filled_pair_above_tau_motion_that_passed_is_reported_as_the_finding():
    rows, conclusion = classify_rows(
        [{"index": 0, "action": "filled", "gap": 0.024, "qa": "pass"}],
        tau_motion=0.017,
    )
    assert rows[0]["guard_should_fire"] is True
    assert "did not fire" in conclusion


def test_an_abstained_pair_is_reported_as_reachable():
    rows, conclusion = classify_rows(
        [{"index": 0, "action": "filled", "gap": 0.024, "qa": "abstain"}],
        tau_motion=0.017,
    )
    assert "abstain" in conclusion
    assert "did not fire" not in conclusion


def test_a_refused_pair_is_never_counted_as_a_guard_failure():
    """A needs_key pair was never interpolated, so no QA guard applies to it."""
    rows, conclusion = classify_rows(
        [{"index": 0, "action": "needs_key", "gap": 0.31, "qa": None}],
        tau_motion=0.017,
    )
    assert rows[0]["guard_should_fire"] is False
    assert "did not fire" not in conclusion


def test_a_missing_gap_is_stated_not_silently_zeroed():
    """Absence of a key is not evidence — the hot-cell lesson. A pair whose gap
    the server did not send must not be scored as 'below tau'."""
    rows, _ = classify_rows(
        [{"index": 0, "action": "filled", "gap": None, "qa": "pass"}],
        tau_motion=0.017,
    )
    assert rows[0]["gap"] == "not reported"
    assert rows[0]["guard_should_fire"] == "unknown"
