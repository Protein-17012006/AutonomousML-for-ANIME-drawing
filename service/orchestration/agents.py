"""The agent adapters. Each has its own input contract, its own authority to
refuse, and its own failure mode — that is the admission test the whole design
rests on, and these three are where it is executable.

Triage is the important one. `classify_gap`'s thresholds were fitted on
suite_widegap_v1 (53 WIDE pairs, LOO 0.660) and KEYS_EDGES is explicitly
uncalibrated — Task 10 stopped without shipping a refit. Off that population
classify_gap does not error; it answers confidently. So when asked about a pair
the gate ACCEPTED, this agent returns what it saw and refuses the key count.
"""
from __future__ import annotations

import re
import time

from service.orchestration import registry
from service.orchestration.models import StepResult

# Vietnamese matters as much as English here: the artist writes Vietnamese, and the
# first version of this pattern missed "ép ... thành pass" — the most natural way to
# say it. On 2026-08-01 the refusal fired only because the PLANNER happened to
# translate the request into English on its way through, which is not a guarantee.
_LOWER_THE_BAR = re.compile(
    r"(?i)"
    r"(force|make|mark|set|flip|turn).{0,32}(pass|green|clean)"
    r"|lower|loosen|relax|override|overrule|bypass"
    r"|(ép|buộc|chuyển|đổi|sửa|ghi|đánh dấu|cho|để|làm cho).{0,32}(pass|đạt|xanh)"
    r"|bỏ qua|hạ ngưỡng|hạ chuẩn|nới|cho qua|bỏ abstain|tắt qa|tắt csq")


class AgentContext:
    """What every handler is given: the session state, an optional LLM callable, and
    the artist's ORIGINAL words.

    `goal` matters for safety. The planner paraphrases, and a paraphrase can launder
    a request: on 2026-08-01 "ép tất cả các cặp thành pass" reached qa_csq as "what is
    your calibrated verdict for pair 3?", so the refusal never fired and the agent
    declined for an unrelated reason. An agent that guards a boundary must be able to
    read what the artist actually asked, not only what the planner chose to relay."""

    __slots__ = ("state", "ask_fn", "goal")

    def __init__(self, state: dict, ask_fn=None, goal: str = ""):
        self.state = state
        self.ask_fn = ask_fn
        self.goal = goal or ""


def _pair_by_index(state: dict, index):
    if not isinstance(index, int):
        return None
    return {p.index: p for p in state["result"].pairs}.get(index)


def _result(step, status, says, payload=None, started=0.0, handoff=None):
    return StepResult(
        step_id=step.id, target=step.target, kind="agent", status=status,
        says=says, payload=payload or {},
        ms=int((time.monotonic() - started) * 1000) if started else 0,
        handoff=handoff)


# --- Triage -----------------------------------------------------------------

def _diagnose(a, b, index: int, ask_fn, key_vlm_fn=None, tau_gate=None) -> dict:
    """Run the real triage service on two retained keys. Pure of the pipeline."""
    from inbetween_copilot.domain.states import PlanAction
    from inbetween_copilot.pipeline.plan_models import PairPlan
    from inbetween_copilot.signals.motion import gap_score
    from inbetween_copilot.triage.brief import LLMBriefWriter, TemplateBriefWriter
    from inbetween_copilot.triage.service import TriagePair
    from service.infrastructure.engines import BOX_TAU_HOLD, BOX_TAU_SNAP

    gap = float(gap_score(a, b))
    pair_plan = PairPlan(index=index, gap=gap, regime="small",
                         action=PlanAction.FILL, keys_to_request=0,
                         tau_gate=tau_gate)
    writer = LLMBriefWriter(ask_fn) if ask_fn is not None else TemplateBriefWriter()
    # Same eyes the run had. Without this the on-demand diagnosis was
    # scalar-only and would quietly contradict the stored one.
    service = TriagePair(tau_hold=BOX_TAU_HOLD, tau_snap=BOX_TAU_SNAP,
                         brief_writer=writer, key_vlm_fn=key_vlm_fn)
    return service.execute(a, b, pair_plan).to_payload()


def triage_agent(ctx: AgentContext, step) -> StepResult:
    started = time.monotonic()
    index = step.args.get("index")
    pair = _pair_by_index(ctx.state, index)
    if pair is None:
        return _result(step, "refused",
                       f"There is no pair {index} in this session, so I have "
                       "nothing to diagnose.", started=started)

    stored = getattr(pair, "triage", None)
    if isinstance(stored, dict) and stored:
        # On-population: the gate refused this pair and triage already ran on it.
        #
        # The MEASUREMENTS stay frozen — regenerating a diagnosis can contradict
        # what is on screen, the failure Spec 4 closed. The ANSWER is written for
        # THIS question: returning `brief` replayed one string written during the
        # pipeline, so two different questions about one pair came back
        # byte-identical and neither was about what was asked.
        from inbetween_copilot.triage.answer import answer_refusal
        overlays = ctx.state.get("pair_keys") or {}
        says = answer_refusal(
            ctx.goal, stored, ctx.ask_fn, index=index,
            overlay=bool(overlays.get(index) or overlays.get(str(index))))
        return _result(step, "ok", says, payload=dict(stored), started=started)

    keys = ctx.state.get("keys") or []
    if not isinstance(index, int) or index < 0 or index + 1 >= len(keys):
        return _result(step, "refused",
                       "I do not have both key drawings for that pair in this "
                       "session, so I cannot diagnose it.", started=started)

    try:
        payload = _diagnose(keys[index], keys[index + 1], index, ctx.ask_fn,
                            getattr(ctx.state.get("eng"), "key_vlm_fn", None),
                            getattr(ctx.state.get("cfg"), "tau_gate", None))
    except Exception as exc:            # noqa: BLE001 — an agent reports, never raises
        return _result(step, "error", f"Triage failed: {exc}", started=started)

    # Off-population. Keep the MEASUREMENTS, drop the PRESCRIPTION.
    #
    # The brief is not commentary that happens to mention a number — its whole job
    # is to prescribe ("draw N breakdown keys at the extremes"). Emitting it while
    # refusing the key count would contradict the refusal in the same breath, which
    # is precisely the confident-but-unverified answer this branch exists to stop.
    # `cls` and `evidence` are measurements of the two drawings, so they survive.
    payload.pop("brief", None)
    payload.pop("keys_suggested", None)
    payload["out_of_population"] = True
    payload["withheld"] = (
        "keys_suggested and the drawing brief: KEYS_EDGES is uncalibrated and "
        "classify_gap was fitted on wide, gate-refused pairs; this pair was "
        "accepted by the gate.")
    ev = payload.get("evidence") or {}
    facts = ", ".join(f"{k}={v}" for k, v in ev.items() if v is not None)

    # CORRECTION 2: point at perception ONLY when perception actually has a
    # finding for this pair. Otherwise this is a promise of an artefact that does
    # not exist — the defect fixed on 2026-08-01.
    exp = ctx.state.get("explanations") or {}
    info = exp.get(index) or exp.get(str(index)) or {}
    has_finding = bool(isinstance(info, dict) and info.get("explanation"))

    says = (
        f"What I can measure: this reads as {payload.get('cls', 'unclassified')}"
        + (f" ({facts})" if facts else "")
        + ". What I will not give you is a key count or a drawing brief. My key "
          "budget was fitted on pairs the gate REFUSED, and the gate accepted this "
          "one — a prescription from me here would look confident and be "
          "unverified."
        + (" Perception did examine this pair, so I am passing it over."
           if has_finding else
           " Nobody examined the frames of this pair either, so I have nothing "
           "further to hand you.")
    )
    handoff = ({"to": "perception", "args": {"index": index},
                "why": "the gate accepted this pair, so perception has frames "
                       "to read and a finding on record"}
               if has_finding else None)
    return _result(step, "refused", says, payload=payload, started=started,
                   handoff=handoff)


# --- Perception -------------------------------------------------------------

def perception_agent(ctx: AgentContext, step) -> StepResult:
    started = time.monotonic()
    index = step.args.get("index")
    exp = ctx.state.get("explanations") or {}
    info = exp.get(index) or exp.get(str(index))
    if not isinstance(info, dict) or not info:
        return _result(step, "refused",
                       f"I did not examine pair {index}. I only look at pairs that "
                       "were filled and then flagged or abstained — a refused pair "
                       "has no frames for me to read.", started=started)
    says = (f"{info.get('err_type', 'defect')} in region "
            f"{info.get('region', 'unknown')}"
            + (f": {info['explanation']}" if info.get("explanation") else ""))
    return _result(step, "ok", says, payload=dict(info), started=started)


# --- QA / CSQ ---------------------------------------------------------------

def qa_csq_agent(ctx: AgentContext, step) -> StepResult:
    started = time.monotonic()
    # Check the ARTIST'S OWN WORDS as well as the planner's relay — a paraphrase
    # must not be able to launder a request to move the bar.
    if _LOWER_THE_BAR.search(f"{step.ask or ''}\n{ctx.goal}"):
        return _result(step, "refused",
                       "I will not move the bar. The pass/abstain/flag split is a "
                       "conformally calibrated verdict with a coverage guarantee, "
                       "not a threshold anyone may slide — changing it would void "
                       "the guarantee that makes the verdict worth anything.",
                       started=started)
    index = step.args.get("index")
    pair = _pair_by_index(ctx.state, index)
    if pair is None:
        return _result(step, "refused",
                       f"There is no pair {index} in this session.", started=started)
    qa = getattr(pair, "qa", None)
    if qa is None:
        return _result(step, "refused",
                       f"Pair {index} has no QA verdict — it was never filled.",
                       started=started)
    payload = {"status": qa.status, "reason": getattr(qa, "reason", "")}
    return _result(step, "ok",
                   f"pair {index}: {qa.status}"
                   + (f" ({payload['reason']})" if payload["reason"] else ""),
                   payload=payload, started=started)


# --- Cut Survey -------------------------------------------------------------
#
# This agent INVENTS NO SCORE. It orders over verdicts that are already
# calibrated — the conformal CSQ status and the tau gate's action — but the
# ONLY order it can support is position in the cut: the sequence the artist
# will draw them in. Bucket (flag / needs_key / abstain) is a REPORTING label,
# never a priority tier — nothing here calibrates severity, so ranking a
# flagged pair above (or below) a refused one would be invented, not derived.
# Fix round 1 (2026-08-02): the first cut sorted by bucket type before
# position, which silently ranked flag above needs_key while the `says` text
# denied doing so. work_order is now positional across ALL actionable
# buckets, full stop.
#
# THREE POPULATIONS, kept distinct (fix round 4, 2026-08-02). Rounds 2 and 3
# each patched one symptom of the same defect: the body carried only two
# lists and used the wrong one as a proxy for "evaluated".
#
#   1. HANDED IN   every object in `result.pairs`               -> n_pairs
#   2. READ        its index coerced to an int                  -> n_pairs - unreadable
#   3. EVALUATED   read AND placed in a known bucket            -> n_evaluated
#
# (3) is a strict subset of (2): a pair can have a perfectly good index and
# still carry a verdict this agent does not recognise, in which case nothing
# evaluated it. Round 3's `readable` was population (2) and the prose said
# "all passed" about it — a claim only population (3) can license.
#
# So: every artist-facing sentence below counts what WAS evaluated. What was
# not evaluated is derived by SUBTRACTING the evaluated from the handed-in,
# never by adding up the failure modes we happen to know about. A fourth
# reason for a pair going unevaluated therefore lands in `not_evaluated`
# automatically — it cannot be silently absorbed into a pass claim, because
# no pass claim is ever computed from a total minus known excuses.

_BUCKETS = ("flag", "needs_key", "abstain", "pass")
_ACTIONABLE = ("flag", "needs_key", "abstain")

_WHY = {
    "flag": "CSQ flagged the generated frames here.",
    "needs_key": "The gate refused this pair; it is waiting on a key from you.",
    "abstain": "CSQ could not decide; this one needs your eye.",
}

# Why a handed-in pair never reached a bucket. These are labels for the ARTIST;
# the accounting does not depend on this map being complete — see `_UNATTRIBUTED`.
_NO_INDEX = "no_usable_index"
_NO_VERDICT = "no_recognised_verdict"
_UNATTRIBUTED = "reason_not_recorded"

_NOT_EVALUATED_WHY = {
    _NO_INDEX: "had no usable index",
    _NO_VERDICT: "carried no verdict I recognise",
    _UNATTRIBUTED: "dropped out for a reason I did not record",
}

_WITHHELD = ("any severity ordering — within a bucket or across bucket types. "
             "No calibrated basis says one flagged pair is worse than another, "
             "or that flag outranks needs_key (or the reverse); work_order is "
             "positional only.")


def _bucket_for(pair) -> str:
    """A pair's bucket, from calibrated state only. '' when it has neither."""
    if str(getattr(pair, "action", "") or "") == "needs_key":
        return "needs_key"
    qa = getattr(pair, "qa", None)
    status = str(getattr(qa, "status", "") or "") if qa is not None else ""
    return status if status in ("flag", "abstain", "pass") else ""


def _account(n_pairs: int, n_evaluated: int, reasons: dict) -> tuple:
    """How many pairs were NOT evaluated, and why — as (total, reasons).

    Extracted so the round-4 property can actually FAIL a test. `total` is the
    handed-in count MINUS the evaluated count; it is never the sum of the
    reasons we happened to record. Inside `cut_survey_agent` the two are equal
    for every reachable input, so no test driving the agent can tell which one
    produced the number — the re-reviewer mutated the derivation to
    `sum(reasons.values())` and all 19 tests passed. Here the caller supplies
    both, so a breakdown that does not add up is expressible, and the rule that
    the subtraction wins is observable.

    Any shortfall is reported rather than dropped: a future code path that
    skips a pair without recording why still costs the artist a sentence."""
    total = n_pairs - n_evaluated
    unattributed = total - sum(reasons.values())
    if unattributed > 0:
        reasons = {**reasons, _UNATTRIBUTED: unattributed}
    return total, reasons


def _not_evaluated_clause(total: int, reasons: dict) -> str:
    """The one sentence that owns population (1) minus population (3).

    It never says "pass" and never says "clean": these pairs were handed in and
    then not looked at. `reasons` is a breakdown for the artist, not the source
    of `total` — an unlabelled reason still gets counted and still gets said."""
    parts = ", ".join(
        f"{n} {_NOT_EVALUATED_WHY.get(key, _NOT_EVALUATED_WHY[_UNATTRIBUTED])}"
        for key, n in reasons.items() if n)
    return (f"{total} pair(s) I could not evaluate at all"
            + (f" ({parts})" if parts else "")
            + " — that is NOT a pass, it is data I never read. They are "
              "excluded from every count above.")


def cut_survey_agent(ctx: AgentContext, step) -> StepResult:
    started = time.monotonic()
    result = ctx.state.get("result")
    pairs = list(getattr(result, "pairs", None) or [])

    # Checked before the pairs are read, and deliberately not merged into the
    # nothing-evaluated rule below: this refuses because the CHANNEL was blind,
    # which is true of a degraded run whether or not any pairs arrived, and it
    # withholds even the accounting because those verdicts are not about the
    # drawings at all. The rule below refuses for the opposite reason — the
    # pairs are real and none of them could be used.
    #
    # The refusal that makes this an agent and not a sort function. Verified live
    # 2026-08-01: with :8001 down every pair abstains `vlm_unavailable`.
    if ctx.state.get("qa_degraded"):
        return _result(
            step, "refused",
            "I will not order this cut. The QA channel was unavailable for this "
            "run, so the pairs abstained for a reason that has nothing to do with "
            "your drawings — a work order built on those verdicts would read as "
            "sensible and mean nothing. Re-run the cut once the detector is back up.",
            payload={"qa_degraded": True}, started=started)

    # ONE pass over the handed-in pairs, and it produces population (3)
    # directly: a pair is appended to `evaluated` only when its index was read
    # AND a known bucket was found for it. Everything else is a `continue`
    # with a recorded reason. Adding a future reason means adding one more
    # branch here; it cannot make a pair count as evaluated by omission.
    #
    # Both reads are defensive. `getattr(pair, "index", None)` never raises
    # even on an object with no attributes at all (round-2's AttributeError),
    # so a bare object lands in (TypeError, ValueError) like a bad value does.
    # `_bucket_for` reads `.action`/`.qa` through getattr for the same reason.
    evaluated: list = []
    reasons: dict = {}
    for pair in pairs:
        try:
            idx = int(getattr(pair, "index", None))
        except (TypeError, ValueError):
            reasons[_NO_INDEX] = reasons.get(_NO_INDEX, 0) + 1
            continue
        bucket = _bucket_for(pair)
        if not bucket:
            reasons[_NO_VERDICT] = reasons.get(_NO_VERDICT, 0) + 1
            continue
        evaluated.append((idx, pair, bucket))
    evaluated.sort(key=lambda t: t[0])

    # The authoritative count of what was NOT evaluated is the total minus the
    # evaluated — never the sum of `reasons`. If the two ever disagree (a
    # future `continue` that forgets to record why), the difference is still
    # reported, under a reason that says exactly that. `_account` owns that
    # rule so it can be tested where a disagreement is expressible.
    n_evaluated = len(evaluated)
    n_not_evaluated, reasons = _account(len(pairs), n_evaluated, reasons)

    buckets: dict = {name: [] for name in _BUCKETS}
    keys_outstanding = 0
    for idx, pair, bucket in evaluated:
        buckets[bucket].append(idx)
        if bucket == "needs_key":
            try:
                keys_outstanding += int(getattr(pair, "keys_requested", 0) or 0)
            except (TypeError, ValueError):
                pass

    # Positional across ALL actionable buckets: bucket is a reporting label,
    # not a priority tier. Choosing a single first_index IS a ranking, and the
    # only ranking this agent can defend is "the order you will draw them in."
    work_order = [{"index": idx, "bucket": bucket, "why": _WHY[bucket]}
                  for idx, _pair, bucket in evaluated if bucket in _ACTIONABLE]

    payload = {"work_order": work_order, "buckets": buckets,
               "keys_outstanding": keys_outstanding, "n_pairs": len(pairs),
               "n_evaluated": n_evaluated, "not_evaluated": n_not_evaluated,
               "not_evaluated_reasons": dict(reasons),
               "unreadable": reasons.get(_NO_INDEX, 0), "withheld": _WITHHELD}

    # THE RULE, and there is only one: A SURVEY THAT EVALUATED NOTHING DOES NOT
    # RETURN A VERDICT. Zero pairs handed in and N pairs handed in that all
    # turned out to be unusable are the SAME epistemic state — no verdict, no
    # work order, nothing actionable — and they differ only in how many objects
    # arrived. Do not re-split this into "empty session" and "nothing usable":
    # splitting it is what let the unusable case answer `ok` for a round while
    # its own prose said it had no verdict.
    #
    # `status` is the machine-readable half of the answer. `ok` here would tell
    # service.py's synthesis prompt "[answered]" (_AGENT_NOTE["ok"]) and render
    # the transcript entry as kind `reply` (dispatch.py's _ENTRY_KIND_FOR),
    # while the prose said the opposite — the same claim-stronger-than-the-data
    # defect this agent has now been patched for three rounds, just moved into
    # the field prose cannot correct.
    #
    # The payload still travels: models.py's own contract says a `refused`
    # result "may still carry what it was willing to provide", and triage_agent
    # is the precedent (measurements kept, prescription withheld). The
    # accounting IS what it was willing to provide — refusing to say it too
    # would hide the very thing that explains the refusal. `first_index` stays
    # absent, as it is on every path with no work.
    if not evaluated:
        says = (
            "This session has no pairs, so there is no work to order."
            if not pairs else
            f"I will not give you a verdict on this cut. I evaluated none of "
            f"the {len(pairs)} pair(s) in it, so there is nothing for a verdict "
            f"to be about. {_not_evaluated_clause(n_not_evaluated, reasons)}")
        return _result(step, "refused", says, payload=payload, started=started)

    if not work_order:
        # Everything evaluated, and every evaluated pair passed. Note what this
        # does NOT say when some pairs went unevaluated: not "all N passed",
        # not "the rest passed" — only the evaluated pairs are in the verdict.
        says = (f"Of the {n_evaluated} pair(s) I actually evaluated, all passed. "
                f"{_not_evaluated_clause(n_not_evaluated, reasons)}"
                if n_not_evaluated else
                f"All {len(pairs)} pairs passed. There is nothing in this "
                "cut that needs your attention.")
        return _result(step, "ok", says, payload=payload, started=started)

    # Only offered when there IS work — an absent field refuses a reference to it
    # with a stated reason, which is the honest answer to "where do I start?"
    payload["first_index"] = work_order[0]["index"]
    counts = ", ".join(f"{len(buckets[n])} {n}" for n in _ACTIONABLE if buckets[n])
    says = (
        f"{counts}. Start at pair {payload['first_index']} — "
        f"{_WHY[work_order[0]['bucket']]} I order the whole work order by "
        "position in the cut, because that is the order you will draw them, not "
        "because the earlier one is worse: nothing here calibrates severity, and "
        "I do not rank a flagged pair above a refused one or the reverse — the "
        "bucket is a label, not a priority."
        + (f" {keys_outstanding} key(s) are still outstanding."
           if keys_outstanding else "")
        + (f" {_not_evaluated_clause(n_not_evaluated, reasons)}"
           if n_not_evaluated else ""))
    return _result(step, "ok", says, payload=payload, started=started)


registry.register_agent("triage", triage_agent)
registry.register_agent("perception", perception_agent)
registry.register_agent("qa_csq", qa_csq_agent)
registry.register_agent("cut_survey", cut_survey_agent)


def run_triage_for_chat(state: dict, index: int, message: str, ask_fn) -> str:
    """Adapter so ORDINARY CHAT reaches the same handler Plan mode uses.

    Chat cannot import this module (the assistant -> orchestration edge is
    one-way), so service/app.py binds this at composition time. Going through
    `triage_agent` rather than reimplementing is the point: the two modes gave
    two different answers about one pair once already (e0ab729d)."""
    from service.orchestration.models import Step

    result = triage_agent(
        AgentContext(state=state, ask_fn=ask_fn, goal=message),
        Step(id=0, target="triage", kind="agent", ask=message,
             args={"index": index}))
    return result.says
