from unittest.mock import MagicMock

from service.orchestration.agents import AgentContext, cut_survey_agent
from service.orchestration.models import Step


def _pair(index, action="filled", qa_status="pass", keys_requested=0):
    p = MagicMock()
    p.index = index
    p.action = action
    p.keys_requested = keys_requested
    if action == "needs_key":
        p.qa = None
    else:
        p.qa = MagicMock()
        p.qa.status = qa_status
        p.qa.reason = ""
    return p


def _state(pairs, qa_degraded=False):
    result = MagicMock()
    result.pairs = pairs
    return {"result": result, "keys": [], "chat": [], "explanations": {},
            "qa_degraded": qa_degraded}


def _run(state):
    return cut_survey_agent(AgentContext(state=state),
                            Step(1, "cut_survey", "agent", args={}))


def test_it_buckets_every_pair_by_its_calibrated_verdict():
    out = _run(_state([_pair(0, action="needs_key", keys_requested=2),
                       _pair(1, qa_status="flag"),
                       _pair(2, qa_status="abstain"),
                       _pair(3, qa_status="pass")]))
    assert out.status == "ok"
    assert out.payload["buckets"] == {"flag": [1], "needs_key": [0],
                                      "abstain": [2], "pass": [3]}
    assert out.payload["n_pairs"] == 4


def test_within_a_bucket_the_order_is_position_in_the_cut():
    out = _run(_state([_pair(2, qa_status="flag"), _pair(0, qa_status="flag"),
                       _pair(1, qa_status="flag")]))
    assert out.payload["buckets"]["flag"] == [0, 1, 2]
    assert out.payload["first_index"] == 0


def test_a_passing_pair_is_reported_but_is_not_WORK():
    out = _run(_state([_pair(0, qa_status="pass"), _pair(1, qa_status="flag")]))
    assert out.payload["buckets"]["pass"] == [0]
    assert [w["index"] for w in out.payload["work_order"]] == [1]


def test_flag_and_needs_key_are_NOT_forced_into_one_ranking():
    """There is no calibrated basis to say which kind of work is worse, and the
    agent must say so rather than imply an order it cannot support. Bucket type
    must not act as a priority tier: with a needs_key pair EARLIER in the cut
    than a flag pair, the needs_key pair leads work_order — sorting by bucket
    type first (flag before needs_key) would silently put the later pair
    first, which is exactly the ranking this agent has no basis for."""
    out = _run(_state([_pair(0, action="needs_key", keys_requested=2),
                       _pair(1, qa_status="flag")]))
    assert [w["index"] for w in out.payload["work_order"]] == [0, 1]
    assert out.payload["first_index"] == 0
    assert "needs_key" in out.payload["withheld"]
    assert "flag" in out.payload["withheld"]


def test_work_order_is_positional_across_all_actionable_buckets_not_grouped_by_bucket():
    """Interleave flag / needs_key / abstain out of bucket-declaration order
    (_ACTIONABLE = flag, needs_key, abstain) and confirm work_order tracks cut
    position only, never bucket type."""
    out = _run(_state([_pair(0, qa_status="flag"),
                       _pair(1, action="needs_key", keys_requested=1),
                       _pair(2, qa_status="abstain"),
                       _pair(3, qa_status="pass")]))
    assert [w["index"] for w in out.payload["work_order"]] == [0, 1, 2]
    assert out.payload["first_index"] == 0


def test_it_says_WHY_it_orders_by_position_and_not_by_severity():
    out = _run(_state([_pair(0, qa_status="flag"), _pair(1, qa_status="flag")]))
    assert "severity" in out.says.lower() or "worse" in out.says.lower()


def test_it_counts_the_keys_still_owed_by_the_artist():
    out = _run(_state([_pair(0, action="needs_key", keys_requested=2),
                       _pair(1, action="needs_key", keys_requested=1),
                       _pair(2, qa_status="pass")]))
    assert out.payload["keys_outstanding"] == 3


def test_it_REFUSES_the_whole_work_order_when_the_qa_channel_was_down():
    """With :8001 down every pair abstains for a reason that has nothing to do
    with the drawings; an order built on that reads sensible and means nothing."""
    out = _run(_state([_pair(0, qa_status="abstain"),
                       _pair(1, qa_status="abstain")], qa_degraded=True))
    assert out.status == "refused"
    assert "first_index" not in out.payload
    assert "work_order" not in out.payload
    assert "re-run" in out.says.lower() or "rerun" in out.says.lower()


def test_it_refuses_a_session_with_no_pairs():
    out = _run(_state([]))
    assert out.status == "refused"


def test_an_all_passing_cut_reports_nothing_to_do_and_offers_no_first_index():
    out = _run(_state([_pair(0, qa_status="pass"), _pair(1, qa_status="pass")]))
    assert out.status == "ok"
    assert out.payload["work_order"] == []
    assert "first_index" not in out.payload


def test_the_payload_is_json_safe():
    """It travels into a TranscriptEntry and out through SSE."""
    import json
    out = _run(_state([_pair(0, action="needs_key", keys_requested=2),
                       _pair(1, qa_status="flag")]))
    assert json.loads(json.dumps(out.payload))["first_index"] == out.payload["first_index"]


def test_importing_the_module_registers_the_survey_agent():
    from service.orchestration import registry
    assert registry.resolve("cut_survey").handler is not None
