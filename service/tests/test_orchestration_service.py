from unittest.mock import MagicMock

from service.orchestration.service import run_goal


def _pair(index, action="needs_key", qa_status="abstain", triage=None):
    p = MagicMock()
    p.index = index
    p.action = action
    p.route = None
    p.keys_requested = 2
    p.qa = MagicMock()
    p.qa.status = qa_status
    p.qa.reason = ""
    p.correction = None
    p.triage = triage
    return p


def _state():
    stored = {"cls": "pose_snap", "keys_suggested": 2, "confidence": "medium",
              "evidence": {"gap": 0.043}, "brief": "Place a breakdown at the overshoot."}
    result = MagicMock()
    result.pairs = [_pair(0, triage=stored), _pair(1, action="filled")]
    result.n_autopass = 0
    result.n_corrected = 0
    result.flagged = []
    result.abstained = [1]
    result.keys_requested_total = 2
    return {"result": result, "keys": [], "chat": [], "explanations": {}}


_PLAN = """{"steps": [
    {"target": "triage", "kind": "agent", "ask": "why refused?", "args": {"index": 0}},
    {"target": "open_board", "kind": "tool", "args": {"index": 0}},
    {"target": "rerun_session", "kind": "tool", "args": {"smoothness": 1}}
]}"""


def test_the_demo_goal_end_to_end():
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "Draw 2 keys at the overshoot. Board is open; rerun is waiting.", "tool": null}'

    out = run_goal(_state(), "why was pair 0 refused, open it, rerun smoothness 1", [],
                   plan_ask_fn=lambda p: _PLAN, say_ask_fn=say)
    assert out["orchestrated"] is True
    assert len(out["steps"]) == 3
    assert len(out["confirm_queue"]) == 1
    assert out["confirm_queue"][0]["tool"] == "rerun_session"
    assert "overshoot" in out["say"]


def test_the_step_results_reach_the_synthesis_prompt():
    """One goal, several sub-tasks, recombined — the criterion, at the top level."""
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "ok", "tool": null}'

    run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN, say_ask_fn=say)
    prompt = seen["p"]
    assert "triage" in prompt
    assert "overshoot" in prompt          # the agent's own words
    assert "rerun_session" in prompt
    assert "waiting on your confirmation" in prompt


def test_a_queued_step_is_also_offered_as_the_single_action_for_old_clients():
    out = run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN,
                   say_ask_fn=lambda p: '{"say": "ok", "tool": null}')
    assert out["action"]["tool"] == "rerun_session"
    assert out["action"]["needs_confirm"] is True


def test_no_planner_falls_through_to_single_turn_chat():
    out = run_goal(_state(), "how many pairs?", [], plan_ask_fn=None,
                   say_ask_fn=lambda p: '{"say": "You have 2 pairs.", "tool": null}')
    assert out["orchestrated"] is False
    assert out["steps"] == []
    assert out["say"] == "You have 2 pairs."


def test_an_unplannable_goal_falls_through_to_single_turn_chat():
    out = run_goal(_state(), "hello", [], plan_ask_fn=lambda p: '{"steps": []}',
                   say_ask_fn=lambda p: '{"say": "Hi.", "tool": null}')
    assert out["orchestrated"] is False
    assert out["say"] == "Hi."


def test_a_failing_synthesis_still_reports_the_steps():
    def boom(prompt):
        raise RuntimeError("deepseek exploded")

    out = run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN, say_ask_fn=boom)
    assert out["orchestrated"] is True
    assert out["say"], "a synthesis failure must not yield an empty reply"
    assert "rerun_session" in out["say"] or "confirmation" in out["say"].lower()


def test_the_transcript_is_persisted_on_the_state():
    from service.orchestration.transcript import entries_for
    state = _state()
    run_goal(state, "g", [], plan_ask_fn=lambda p: _PLAN,
             say_ask_fn=lambda p: '{"say": "ok", "tool": null}')
    entries = entries_for(state)
    assert entries
    assert entries[0]["frm"] == "orchestrator"
    assert any(e["to"] == "orchestrator" for e in entries)


def test_live_entries_are_streamed_to_the_callback():
    seen = []
    run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN,
             say_ask_fn=lambda p: '{"say": "ok", "tool": null}', on_entry=seen.append)
    assert len(seen) == 6          # three steps, ask + reply each


def test_utterances_are_yielded_BEFORE_the_synthesis_runs():
    """Liveness: the transcript must not be a recording replayed after the turn.
    The synthesis call must not have happened while entries are still arriving.

    Counting ask_fn calls is NOT enough any more, and the difference matters.
    Since 2026-08-03 the triage specialist writes its own answer through the same
    say_ask_fn, so a bare call count no longer isolates synthesis — it would go
    green on a run where synthesis had not happened and red on one where it had.
    Only prompts carrying the decide_agent contract count as synthesis."""
    from service.orchestration.service import run_goal_stream

    prompts = []

    def say(prompt):
        prompts.append(prompt)
        return '{"say": "ok", "tool": null}'

    def n_synthesis():
        return sum(1 for p in prompts if "Reply STRICT JSON only:" in p)

    stream = run_goal_stream(_state(), "g", [], plan_ask_fn=lambda p: _PLAN,
                             say_ask_fn=say)
    kind, payload = next(stream)
    assert kind == "agent"
    assert payload.frm == "orchestrator"
    assert n_synthesis() == 0, "synthesis ran before the first utterance was emitted"
    # ...and the specialist really did do its own thinking, rather than the
    # director answering on its behalf from the session facts.
    assert any("gap-triage specialist" in p for p in prompts)

    kinds = [kind] + [k for k, _ in stream]
    assert kinds[-1] == "decision"
    assert kinds.count("agent") == 6


def test_an_ok_TOOL_is_never_described_to_synthesis_as_already_done():
    """Live run 2026-08-01 produced "Export bundle đã được thực hiện thành công rồi"
    and "Đã mở bảng đánh giá cặp 1 thành công" — both claimed an action ran that
    dispatch never executes."""
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "ok", "tool": null}'

    plan = '{"steps": [{"target": "export_bundle", "kind": "tool", "args": {}}]}'
    run_goal(_state(), "export it", [], plan_ask_fn=lambda p: plan, say_ask_fn=say)
    prompt = seen["p"]
    assert "has NOT run yet" in prompt
    assert "never say it is done" in prompt
    assert "NOTHING in this list has been executed" in prompt


def test_the_specialists_MEASUREMENTS_reach_the_writer_not_only_its_prose():
    """The numbers reached the SCREEN and not the writer.

    `_findings_block` concatenated `r.says` alone, so the whole payload — the
    class, the key budget, the gap, a tool's arguments — was dropped before
    synthesis. It rides in the transcript entry's `data`, so the artist could
    read `gap 0.043` on screen while the model writing the answer had only
    prose to paraphrase. That is the SPEC 5 defect one level down: the facts
    must point at the measurement, not restate a sentence about it.
    """
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "ok", "tool": null}'

    run_goal(_state(), "g", [], plan_ask_fn=lambda p: _PLAN, say_ask_fn=say)
    prompt = seen["p"]
    assert "cls=pose_snap" in prompt
    assert "keys_suggested=2" in prompt
    assert "gap=0.043" in prompt              # one level into `evidence`
    assert "index=0" in prompt                # a tool step's own arguments


def test_prose_already_in_says_is_not_repeated_as_a_measurement():
    """`brief`, `explanation` and `withheld` are sentences the specialist has
    already spoken through `says`. Repeating them under `measured:` would pad
    the context with a second copy of the same words and push the actual
    numbers further from the model's attention."""
    from service.orchestration.models import StepResult
    from service.orchestration.service import _findings_block
    result = StepResult(1, "triage", "agent", "ok", says="Draw 2 keys.",
                        payload={"cls": "pose_snap", "keys_suggested": 2,
                                 "brief": "Place a breakdown at the overshoot.",
                                 "withheld": "keys_suggested and the brief"})
    block = _findings_block([result])
    assert "cls=pose_snap" in block
    assert "brief=" not in block
    assert "withheld=" not in block


# --- the verifier, wired into synthesis --------------------------------------

_REJECTING_PLAN = ('{"steps": [{"target": "image_edit", "kind": "tool", '
                   '"args": {"index": 9}}]}')
# Tool-only: `say_ask_fn` is ALSO the specialists' `ask_fn`, so a plan with an
# agent step makes triage call it too and "how many times was the director
# asked" stops being answerable by counting.
_TOOL_ONLY_PLAN = ('{"steps": [{"target": "open_board", "kind": "tool", '
                   '"args": {"index": 0}}]}')


def _synthesis_prompts(prompts):
    return [p for p in prompts if "AGENT FINDINGS THIS TURN" in p]


def test_a_clean_reply_costs_no_second_call():
    """The check is free when nothing is wrong. If it re-asked every turn it
    would double the latency of the whole feature to catch a rare defect."""
    calls = []

    def say(prompt):
        calls.append(prompt)
        return '{"say": "The board is ready to open at pair 0.", "tool": null}'

    run_goal(_state(), "g", [], plan_ask_fn=lambda p: _TOOL_ONLY_PLAN, say_ask_fn=say)
    assert len(_synthesis_prompts(calls)) == 1


def test_a_promised_artefact_that_does_not_exist_is_rewritten_once():
    """The defect class that has bitten three times, now caught by a machine."""
    replies = ['{"say": "I marked it up for you in pair_9_annotated.png.", "tool": null}',
               '{"say": "That pair was refused, so there is no marked frame.", '
               '"tool": null}']
    prompts = []

    def say(prompt):
        prompts.append(prompt)
        return replies[min(len(prompts) - 1, len(replies) - 1)]

    out = run_goal(_state(), "show me the marked frame", [],
                   plan_ask_fn=lambda p: _TOOL_ONLY_PLAN, say_ask_fn=say)
    assert len(_synthesis_prompts(prompts)) == 2, "the director was never asked to fix it"
    assert "REJECTED BY A CHECK" in prompts[1]
    assert "pair_9_annotated.png" in prompts[1]
    assert out["say"] == "That pair was refused, so there is no marked frame."


def test_a_reply_that_stays_wrong_is_downgraded_to_the_plain_summary():
    """`_fallback_say` is blunt, and it is always true. A second wrong answer is
    worse than a plain one."""
    def say(prompt):
        return '{"say": "I marked it up in pair_9_annotated.png.", "tool": null}'

    out = run_goal(_state(), "show me the marked frame", [],
                   plan_ask_fn=lambda p: _TOOL_ONLY_PLAN, say_ask_fn=say)
    assert "pair_9_annotated.png" not in out["say"]
    assert "LLM director offline" in out["say"] or "open_board" in out["say"]


def test_a_soft_violation_buys_a_rewrite_but_never_a_downgrade():
    """Rule C is the one that can cry wolf. It may ask for a better answer; it
    may not throw one away — a false alarm must not cost the artist the reply."""
    prompts = []

    def say(prompt):
        prompts.append(prompt)
        return '{"say": "The gap measured 0.9999, well over the line.", "tool": null}'

    out = run_goal(_state(), "g", [], plan_ask_fn=lambda p: _TOOL_ONLY_PLAN,
                   say_ask_fn=say)
    assert len(_synthesis_prompts(prompts)) == 2   # it did ask for a rewrite
    assert "0.9999" in out["say"]                  # and kept the answer anyway


def test_the_check_writes_itself_into_the_transcript():
    """A mechanism nobody can see is a mechanism nobody can trust."""
    entries = []

    def say(prompt):
        return '{"say": "I marked it up in pair_9_annotated.png.", "tool": null}'

    run_goal(_state(), "show me the marked frame", [],
             plan_ask_fn=lambda p: _TOOL_ONLY_PLAN, say_ask_fn=say,
             on_entry=entries.append)
    checks = [e for e in entries if e.frm == "verifier"]
    assert len(checks) == 1, [e.frm for e in entries]
    assert "pair_9_annotated.png" in checks[0].text


def test_a_refusal_re_enters_the_planner_for_the_tail_end_to_end():
    """The whole loop: plan, a specialist refuses, the planner is asked again with
    what happened, and the replacement runs. `plan_ask_fn` is the seam, so the
    re-entry is visible as a second call carrying the refusal."""
    prompts = []
    first = ('{"steps": [{"target": "triage", "kind": "agent", "args": {"index": 5}},'
             ' {"target": "open_board", "kind": "tool", "args": {"index": 0}}]}')
    second = '{"steps": [{"target": "open_board", "kind": "tool", "args": {"index": 1}}]}'

    def plan(prompt):
        prompts.append(prompt)
        return second if "ALREADY HAPPENED THIS TURN" in prompt else first

    out = run_goal(_state(), "explain pair 5 then open it", [], plan_ask_fn=plan,
                   say_ask_fn=lambda p: '{"say": "ok", "tool": null}')
    assert len(prompts) == 2, "the planner was never asked to reconsider"
    assert "STILL QUEUED: open_board" in prompts[1]
    assert [s["target"] for s in out["steps"]] == ["triage", "open_board"]
    # the REPLANNED arguments, not the ones the dead plan carried
    assert out["steps"][1]["status"] == "ok"


def test_a_rejected_AGENT_step_carries_an_agent_specific_note_not_the_tool_one():
    """dispatch.py builds StepResult(..., "agent", "rejected") whenever an
    AGENT step's late-binding reference fails to resolve — newly reachable on
    this branch. `_AGENT_NOTE` had no "rejected" entry, so `.get(status, "")`
    silently fell back to nothing, leaving the synthesising LLM with raw
    `$`-syntax and a payload key list and no instruction at all."""
    from service.orchestration.models import StepResult
    from service.orchestration.service import _findings_block
    result = StepResult(1, "qa_csq", "agent", "rejected",
                        says="$1.first_index asks step 1 for 'first_index', "
                             "which it did not report. It reported: buckets.")
    block = _findings_block([result])
    line = next(l for l in block.splitlines() if "qa_csq" in l)
    assert "[" in line, line            # a bracketed instruction is present
    # It must be AGENT wording, not the TOOL note leaking onto an agent line:
    # a tool is "proposed"/"refused by the server"; an agent is only ever
    # "asked", and this step never reached it.
    assert "SERVER REFUSED THESE ARGUMENTS" not in line, line
    assert "not proposed" not in line, line


def test_fallback_say_for_a_rejected_agent_does_not_use_tool_language():
    """`_fallback_say` said 'was refused by the server and not proposed' for
    EVERY rejected step regardless of kind — true for a tool (the server
    validated and refused its arguments), false for an agent (its arguments
    could not even be resolved, so nothing was ever proposed to refuse)."""
    from service.orchestration.models import StepResult
    from service.orchestration.service import _fallback_say
    agent_rejected = StepResult(1, "qa_csq", "agent", "rejected",
                                says="the resolver failed")
    out = _fallback_say([agent_rejected])
    assert "qa_csq" in out
    assert "not proposed" not in out
    assert "refused by the server" not in out

    tool_rejected = StepResult(1, "open_board", "tool", "rejected",
                               says="bad index")
    tool_out = _fallback_say([tool_rejected])
    assert "refused by the server" in tool_out   # tool wording is unchanged


def test_an_ok_AGENT_and_an_ok_TOOL_carry_different_notes():
    """An agent that answered really did answer; a tool that is `ok` did not run."""
    seen = {}

    def say(prompt):
        seen["p"] = prompt
        return '{"say": "ok", "tool": null}'

    plan = ('{"steps": [{"target": "triage", "kind": "agent", "args": {"index": 0}},'
            ' {"target": "open_board", "kind": "tool", "args": {"index": 0}}]}')
    run_goal(_state(), "g", [], plan_ask_fn=lambda p: plan, say_ask_fn=say)
    assert "(agent) -> ok [answered]" in seen["p"]
    assert "(tool) -> ok [READY TO PROPOSE" in seen["p"]
