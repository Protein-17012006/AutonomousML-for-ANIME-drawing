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


def _result(step, status, says, payload=None, started=0.0):
    return StepResult(
        step_id=step.id, target=step.target, kind="agent", status=status,
        says=says, payload=payload or {},
        ms=int((time.monotonic() - started) * 1000) if started else 0)


# --- Triage -----------------------------------------------------------------

def _diagnose(a, b, index: int, ask_fn) -> dict:
    """Run the real triage service on two retained keys. Pure of the pipeline."""
    from inbetween_copilot.domain.states import PlanAction
    from inbetween_copilot.pipeline.plan_models import PairPlan
    from inbetween_copilot.signals.motion import gap_score
    from inbetween_copilot.triage.brief import LLMBriefWriter, TemplateBriefWriter
    from inbetween_copilot.triage.service import TriagePair
    from service.infrastructure.engines import BOX_TAU_HOLD, BOX_TAU_SNAP

    gap = float(gap_score(a, b))
    pair_plan = PairPlan(index=index, gap=gap, regime="small",
                         action=PlanAction.FILL, keys_to_request=0)
    writer = LLMBriefWriter(ask_fn) if ask_fn is not None else TemplateBriefWriter()
    service = TriagePair(tau_hold=BOX_TAU_HOLD, tau_snap=BOX_TAU_SNAP,
                         brief_writer=writer)
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
        brief = str(stored.get("brief") or "").strip()
        return _result(step, "ok", brief or f"Diagnosis: {stored.get('cls', '?')}.",
                       payload=dict(stored), started=started)

    keys = ctx.state.get("keys") or []
    if not isinstance(index, int) or index < 0 or index + 1 >= len(keys):
        return _result(step, "refused",
                       "I do not have both key drawings for that pair in this "
                       "session, so I cannot diagnose it.", started=started)

    try:
        payload = _diagnose(keys[index], keys[index + 1], index, ctx.ask_fn)
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
    says = (
        f"What I can measure: this reads as {payload.get('cls', 'unclassified')}"
        + (f" ({facts})" if facts else "")
        + ". What I will not give you is a key count or a drawing brief. My key "
          "budget was fitted on pairs the gate REFUSED, and the gate accepted this "
          "one — a prescription from me here would look confident and be "
          "unverified. For a pair that was filled, ask perception what went wrong "
          "in it instead."
    )
    return _result(step, "refused", says, payload=payload, started=started)


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


registry.register_agent("triage", triage_agent)
registry.register_agent("perception", perception_agent)
registry.register_agent("qa_csq", qa_csq_agent)
