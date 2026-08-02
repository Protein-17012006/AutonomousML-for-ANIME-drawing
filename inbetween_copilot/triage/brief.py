"""Drawing brief for a gate-refused pair: what the human should draw.

template_brief() is the deterministic fallback (stub engines / DeepSeek down /
no key) — the degrade-never-500 pattern from the grounded-/ask design. The LLM
path builds brief_prompt() and sends it through director_llm.make_ask_fn.
"""
from __future__ import annotations

from inbetween_copilot.triage.models import GapTriage
from inbetween_copilot.triage.reading import _CELL_WORDS


class TemplateBriefWriter:
    def __call__(self, triage: GapTriage) -> str:
        return template_brief(triage)


class LLMBriefWriter:
    """LLM strategy decorated with deterministic fallback behavior."""

    def __init__(self, ask_fn, fallback=None):
        self.ask_fn = ask_fn
        self.fallback = fallback or TemplateBriefWriter()

    def __call__(self, triage: GapTriage) -> str:
        try:
            brief = (self.ask_fn(brief_prompt(triage)) or "").strip()
        except Exception:
            brief = ""
        return brief or self.fallback(triage)

_TEMPLATES = {
    "scene_cut": ("These two keys belong to different shots — do not in-between "
                  "across the cut. Start a new cut here and key the first frame "
                  "of the new shot."),
    "camera_move": ("The content matches but the camera moves; draw {k} "
                    "in-between key(s) that carry the BACKGROUND translation "
                    "evenly and keep character-to-background anchoring fixed."),
    "pose_snap": ("This reads as an intentional snap between held poses. If the "
                  "snap is intended, keep it (no in-between). Otherwise draw {k} "
                  "breakdown key(s) at the moment the pose commits."),
    "large_action": ("The action is too large to interpolate safely; draw {k} "
                     "breakdown key(s) at the extreme(s) of the arc — where the "
                     "motion changes direction — then re-run the pair."),
}


def template_brief(t: GapTriage) -> str:
    return _TEMPLATES[t.cls].format(k=max(1, t.keys_suggested))


def brief_prompt(t: GapTriage) -> str:
    """What the director is told before it writes the brief.

    It used to be told three scalars and nothing else, so the best it could
    write was "lift the moving part into a visible arc" — true of almost any
    refused pair, and useless for this one. When the drawings were read, the
    subject and the place are named here so the brief can be about THIS pair.
    """
    evidence = dict(t.evidence or {})
    what = evidence.get("reading_what_moved")
    where = _CELL_WORDS.get(str(evidence.get("hot_cell") or ""))
    observed = ""
    if what:
        observed = f"\nThe vision model looked at the two drawings and saw: {what}"
        if evidence.get("reading_abrupt"):
            observed += ", entering abruptly"
        if evidence.get("reading_note"):
            observed += f". It noted: {evidence['reading_note']}"
        observed += "."
    if where:
        # Measured, and stated as such: the model's own region guess is not
        # reliable at this resolution, so the cell comes from the pixels.
        observed += (f"\nMeasured on the two drawings, the change is concentrated "
                     f"in the {where} of the frame.")
    return (
        "You are an anime in-between supervisor (sakkan). A pair of keyframes was "
        f"refused by the interpolable gate. Diagnosis: class={t.cls}, "
        f"suggested_keys={t.keys_suggested}, evidence={t.evidence}."
        + observed +
        "\nIn 2 short sentences of plain text (no JSON, no markdown), tell the "
        "animator exactly what breakdown key(s) to draw (pose, which extreme of "
        "the arc, what to keep anchored). Name the part that moves and where it "
        "is if you were told them. Be concrete and modest; never claim to have "
        "seen more than two drawings."
    )
