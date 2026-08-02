from unittest.mock import MagicMock

from service.orchestration.agents import AgentContext, cut_survey_agent
from service.orchestration.models import Step, StepResult


class _Bare:
    """A pair-shaped object with NO attributes at all — not even `.index`. This
    reproduces round-2 review's AttributeError: `int(pair.index)` used to raise
    past the (TypeError, ValueError) guard when the attribute was entirely
    absent, not merely present-but-wrong-typed. A MagicMock cannot exercise
    this: it auto-creates any attribute you read from it."""


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


def _pair_without_qa(index, action="filled"):
    """A pair whose index reads perfectly but which carries no QA verdict at
    all, and whose action is not `needs_key` — so nothing evaluated it."""
    p = MagicMock()
    p.index = index
    p.action = action
    p.keys_requested = 0
    p.qa = None
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
    """Discriminating arrangement: abstain@0, flag@1, needs_key@2.

    _ACTIONABLE is declared ("flag", "needs_key", "abstain"), so bucket-first
    grouping would emit flag's pair (1), then needs_key's pair (2), then
    abstain's pair (0) last -> [1, 2, 0], first_index=1. Positional-by-cut
    order gives [0, 1, 2], first_index=0. The two orderings disagree on every
    element here, so this test fails against bucket-first code and cannot
    pass vacuously the way flag@0/needs_key@1/abstain@2 would (those already
    ascend in both orderings' declared sequence)."""
    out = _run(_state([_pair(0, qa_status="abstain"),
                       _pair(1, qa_status="flag"),
                       _pair(2, action="needs_key", keys_requested=1)]))
    assert [w["index"] for w in out.payload["work_order"]] == [0, 1, 2]
    assert out.payload["first_index"] == 0


def test_a_pair_missing_the_index_attribute_entirely_does_not_raise():
    """Regression for round-2: a pair-shaped object with no `.index` at all
    must be reported, not raised. It is silently excluded from every bucket
    (the same deferred-minor behaviour as a non-coercible index) but the call
    itself must still return a StepResult."""
    out = _run(_state([_Bare()]))
    assert isinstance(out, StepResult)
    assert out.payload["n_pairs"] == 1


def test_an_unreadable_pair_is_never_reported_as_having_passed():
    """Regression for round-3: a pair that could not be bucketed at all was
    never reviewed, so it must not be folded into an "all passed" verdict —
    that would tell the artist QA ran clean on data QA never saw. With the
    ONLY pair in the session unreadable, the reply must say it could not be
    read, not that it passed, and `unreadable` must be in the payload so the
    gap is legible rather than silent inside n_pairs."""
    out = _run(_state([_Bare()]))
    assert out.status == "ok"
    assert out.payload["unreadable"] == 1
    assert "all 1 pair" not in out.says.lower()
    assert "passed" not in out.says.lower() or "could not read" in out.says.lower()


def test_the_has_work_reply_also_surfaces_unreadable_pairs():
    """An unreadable pair alongside real work must not be dropped silently —
    understating the count in a way the artist cannot detect is the same
    failure as claiming a false pass, just on the has-work branch.

    THREE unreadable pairs, not one, and one flag pair at index 0: the only
    "3" anywhere in the reply is the unevaluated count, so asserting on it
    cannot pass off some other number. (Round 3's version used one unreadable
    pair and asserted `"1" in says` — but `says` already contains "1 flag" and
    "pair 1", so that assertion held even if the count were dropped entirely.)"""
    out = _run(_state([_pair(0, qa_status="flag"), _Bare(), _Bare(), _Bare()]))
    assert out.payload["unreadable"] == 3
    assert out.payload["not_evaluated"] == 3
    assert out.payload["n_pairs"] == 4
    assert out.payload["n_evaluated"] == 1
    assert "3" in out.says
    assert "no usable index" in out.says.lower() or "unreadable" in out.says.lower()


def test_a_pair_that_was_READ_but_never_BUCKETED_is_not_reported_as_passing():
    """Round-4 Critical. `readable` is not `evaluated`.

    Pair 1's index reads fine, so it survives the index guard — but its
    qa.status matches no known bucket, so nothing ever evaluated it. Counting
    it as "read" and then saying "of the pairs I could read, all passed" is a
    pass verdict over a pair that was never looked at. Every bucket here is
    empty; there is nothing that passed."""
    out = _run(_state([_Bare(), _pair(1, qa_status="weird_unrecognized")]))
    assert out.status == "ok"
    assert out.payload["buckets"] == {"flag": [], "needs_key": [],
                                      "abstain": [], "pass": []}
    assert out.payload["n_pairs"] == 2
    assert out.payload["n_evaluated"] == 0
    assert out.payload["not_evaluated"] == 2
    assert out.payload["unreadable"] == 1        # only the _Bare one
    assert "passed" not in out.says.lower()
    assert "all passed" not in out.says.lower()
    assert "could not read" not in out.says.lower()   # it read one of them fine


def test_an_unrecognised_verdict_alone_does_not_make_an_all_passing_cut():
    """The same defect with the index guard entirely out of the picture: one
    pair, index perfectly readable, verdict unrecognised. Nothing was
    evaluated, so "All 1 pairs passed" is a claim with no data under it."""
    out = _run(_state([_pair(0, qa_status="not_a_real_status")]))
    assert out.payload["n_evaluated"] == 0
    assert out.payload["not_evaluated"] == 1
    assert out.payload["unreadable"] == 0
    assert "passed" not in out.says.lower()


def test_a_pair_with_no_qa_and_a_non_needs_key_action_is_counted_as_not_evaluated():
    """The second deferred Minor, now legible: a pair the gate did not refuse
    but which carries no QA verdict is in no bucket, and must therefore be
    reported as not evaluated rather than vanishing inside n_pairs."""
    out = _run(_state([_pair(0, qa_status="flag"), _pair_without_qa(1)]))
    assert out.payload["n_pairs"] == 2
    assert out.payload["n_evaluated"] == 1
    assert out.payload["not_evaluated"] == 1
    assert out.payload["unreadable"] == 0
    assert out.payload["not_evaluated_reasons"] == {"no_recognised_verdict": 1}
    assert "could not evaluate" in out.says.lower()


def test_the_three_populations_always_account_for_every_handed_in_pair():
    """n_pairs is what was handed in; n_evaluated is what reached a bucket;
    not_evaluated is the remainder — derived by subtraction, so no reason for
    a pair going unevaluated can leak out of the accounting. Every pair in
    every bucket is an evaluated pair and vice versa."""
    out = _run(_state([_pair(0, qa_status="flag"), _Bare(),
                       _pair(2, qa_status="junk"), _pair_without_qa(3),
                       _pair(4, action="needs_key", keys_requested=1),
                       _pair(5, qa_status="pass")]))
    p = out.payload
    assert p["n_pairs"] == 6
    assert p["n_evaluated"] + p["not_evaluated"] == p["n_pairs"]
    assert p["n_evaluated"] == sum(len(v) for v in p["buckets"].values()) == 3
    assert sum(p["not_evaluated_reasons"].values()) == p["not_evaluated"] == 3
    assert p["unreadable"] == 1


def test_it_says_WHY_it_orders_by_position_and_not_by_severity():
    out = _run(_state([_pair(0, qa_status="flag"), _pair(1, qa_status="flag")]))
    assert "severity" in out.says.lower() or "worse" in out.says.lower()


def test_it_counts_the_keys_still_owed_by_the_artist():
    """The passing pair carries keys_requested=5 deliberately. Summing over ALL
    pairs would give 8; only summing over the needs_key bucket gives 3. With
    the passing pair at 0 (as this test had through round 3) both sums give 3,
    so it could not fail on the rule it is named for."""
    out = _run(_state([_pair(0, action="needs_key", keys_requested=2),
                       _pair(1, action="needs_key", keys_requested=1),
                       _pair(2, qa_status="pass", keys_requested=5)]))
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
    # The plain sentence, only ever earned when EVERY handed-in pair was
    # actually evaluated and every one of them passed.
    assert out.says == ("All 2 pairs passed. There is nothing in this cut "
                        "that needs your attention.")
    assert out.payload["n_evaluated"] == out.payload["n_pairs"] == 2
    assert out.payload["not_evaluated"] == 0


def test_the_payload_is_json_safe():
    """It travels into a TranscriptEntry and out through SSE."""
    import json
    out = _run(_state([_pair(0, action="needs_key", keys_requested=2),
                       _pair(1, qa_status="flag")]))
    assert json.loads(json.dumps(out.payload))["first_index"] == out.payload["first_index"]


def test_importing_the_module_registers_the_survey_agent():
    from service.orchestration import registry
    assert registry.resolve("cut_survey").handler is not None
