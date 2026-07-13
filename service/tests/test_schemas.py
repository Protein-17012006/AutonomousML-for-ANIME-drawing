import os
import pytest
from service.sessions.schemas import PairEvent, ResultEvent, SessionCfg, sse
from inbetween_copilot.pipeline.copilot import PairResult, CopilotResult


def test_session_cfg_default_fps():
    """Session default playback fps = 24 (true real-time). NB: a stride-2 reconstruction
    of a ~24fps source plays ~2x fast at 48, so 24 is the correct real-time default."""
    assert SessionCfg().fps == 24


def test_default_cadence_smoothness():
    c = SessionCfg()
    assert c.cadence_fps == 12 and c.smoothness == 2 and c.fps == 24


def test_fps_derived_from_cadence_and_smoothness():
    assert SessionCfg(cadence_fps=8, smoothness=2).fps == 16   # on-3s x2
    assert SessionCfg(cadence_fps=24, smoothness=1).fps == 24  # on-1s Off


def test_explicit_fps_still_honored():
    assert SessionCfg(fps=30).fps == 30


def test_pair_event_from_pair():
    p = PairResult(index=2, action="filled", route="rife", frames=[1], qa=None, keys_requested=0)
    e = PairEvent.from_pair(p)
    assert e.index == 2 and e.action == "filled" and e.route == "rife"


def test_result_event_lists_and_artifacts():
    r = CopilotResult(pairs=[], keys_requested_total=3, flagged=[1], n_autopass=4, n_corrected=0, abstained=[2])
    e = ResultEvent.from_result(r, {"montage": "/x/m.png"})
    assert e.flagged == [1] and e.abstained == [2] and e.artifacts["montage"] == "/x/m.png"


def test_sse_encodes_event_and_data():
    out = sse("ping", ResultEvent.from_result(CopilotResult(pairs=[], keys_requested_total=0, flagged=[], n_autopass=0), {}))
    assert out.startswith("event: ping\ndata: ") and out.endswith("\n\n")


def test_result_event_explanations_default_empty():
    """ResultEvent.from_result with no explanations kwarg → explanations == {}."""
    r = CopilotResult(pairs=[], keys_requested_total=0, flagged=[], n_autopass=0)
    e = ResultEvent.from_result(r, {})
    assert e.explanations == {}


def test_result_event_explanations_round_trip():
    """Explanations dict is preserved and survives JSON serialisation."""
    r = CopilotResult(pairs=[], keys_requested_total=0, flagged=[], n_autopass=0)
    exp = {0: {"err_type": "ghost", "region": "mc", "explanation": "test"}}
    e = ResultEvent.from_result(r, {}, explanations=exp)
    assert e.explanations == exp
    # round-trip through JSON
    import json
    dumped = json.loads(e.model_dump_json())
    # keys become strings in JSON
    assert dumped["explanations"]["0"]["err_type"] == "ghost"


def test_x4_rejected_when_flag_off(monkeypatch):
    """smoothness=4 is rejected when COPILOT_SMOOTHNESS_X4 env flag is not set."""
    monkeypatch.delenv("COPILOT_SMOOTHNESS_X4", raising=False)
    with pytest.raises(ValueError):
        SessionCfg(smoothness=4)


def test_x4_allowed_when_flag_on(monkeypatch):
    """smoothness=4 is allowed when COPILOT_SMOOTHNESS_X4 env flag is set."""
    monkeypatch.setenv("COPILOT_SMOOTHNESS_X4", "1")
    assert SessionCfg(smoothness=4).fps == 12 * 4


def test_sessioncfg_show_defaults_none():
    from service.sessions.schemas import SessionCfg
    assert SessionCfg().show is None


def test_sessioncfg_show_strips_clamps_and_empties_to_none():
    from service.sessions.schemas import SessionCfg
    assert SessionCfg(show="  Wistoria  ").show == "Wistoria"
    assert SessionCfg(show="   ").show is None
    assert len(SessionCfg(show="x" * 200).show) == 64
