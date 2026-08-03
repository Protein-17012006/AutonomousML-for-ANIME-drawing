"""`gap` alone is not a reason. The evidence must carry the threshold it was
compared against — the box runs COPILOT_TAU_GATE=0.05, not thresholds.py's
0.017, so a reader who assumes the code default reads the wrong decision."""
import numpy as np

from inbetween_copilot.domain.states import PlanAction
from inbetween_copilot.pipeline.plan_models import PairPlan
from inbetween_copilot.triage.brief import TemplateBriefWriter
from inbetween_copilot.triage.service import TriagePair


def _pair():
    a = np.zeros((16, 16, 3), np.uint8)
    b = a.copy()
    b[4:8, 4:8] = 255
    return a, b


def _execute(pp):
    a, b = _pair()
    return TriagePair(tau_hold=0.01, tau_snap=0.2,
                      brief_writer=TemplateBriefWriter()).execute(a, b, pp)


def test_evidence_carries_the_tau_the_session_ran():
    pp = PairPlan(index=0, gap=0.058, regime="small",
                  action=PlanAction.NEEDS_KEY, keys_to_request=2, tau_gate=0.05)
    assert _execute(pp).diagnosis.evidence["tau_gate"] == 0.05


def test_evidence_omits_tau_when_the_plan_does_not_know_it():
    pp = PairPlan(index=0, gap=0.058, regime="small",
                  action=PlanAction.NEEDS_KEY, keys_to_request=2)
    assert "tau_gate" not in _execute(pp).diagnosis.evidence


def test_the_plan_records_the_tau_it_gated_each_pair_with():
    from inbetween_copilot.pipeline.plan import build_key_plan

    plan = build_key_plan([0.001, 0.5], ["small", "small"], tau_gate=0.05)
    assert [p.tau_gate for p in plan.pairs] == [0.05, 0.05]
    assert [str(p.action) for p in plan.pairs] == ["fill", "needs_key"]
