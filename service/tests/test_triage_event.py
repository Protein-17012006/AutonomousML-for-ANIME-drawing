import numpy as np

from inbetween_copilot.pipeline.copilot import run_copilot
from service.infrastructure.engines import stub_engines
from service.infrastructure.engine_bundle import _SERVICE_ONLY as _SERVICE_ONLY_KEYS
from service.sessions.runner import run_session
from service.sessions.schemas import PairEvent, SessionCfg


def _keys():
    a = np.zeros((8, 8, 3), np.uint8)
    return [a, a + 1, a + 200]            # last jump exceeds TAU_GATE in stub gap_fn


def test_stub_needs_key_pair_event_carries_triage_with_brief():
    events = []
    res = run_session(_keys(), stub_engines(SessionCfg()),
                      on_pair=lambda p: events.append(PairEvent.from_pair(p)))
    nk = [e for e in events if e.action == "needs_key"]
    assert nk and nk[0].triage is not None
    assert nk[0].triage["cls"] in {"scene_cut", "camera_move", "pose_snap", "large_action"}
    assert len(nk[0].triage["brief"]) > 20


def test_triage_fn_is_a_run_copilot_param_not_service_only():
    assert "triage_fn" not in _SERVICE_ONLY_KEYS
    import inspect
    assert "triage_fn" in inspect.signature(run_copilot).parameters


def test_box_style_triage_builder_degrades_to_template_when_llm_empty():
    from service.infrastructure.engines import make_triage_fn
    import numpy as np
    fn = make_triage_fn(tau_hold=0.01, tau_snap=0.18, ask_fn=lambda prompt: "")
    a = np.zeros((16, 16, 3), np.uint8)
    b = np.full((16, 16, 3), 200, np.uint8)

    class PP:  # matches PairPlan fields the fn reads
        gap, regime = 0.2, "small"

    out = fn(a, b, PP)
    assert out["brief"] and len(out["brief"]) > 20      # template kicked in
