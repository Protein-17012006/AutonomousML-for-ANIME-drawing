"""Builders for pair classification and frame-filling engine adapters."""
from __future__ import annotations

from typing import Any, Callable

from inbetween_copilot.domain.character import CharacterSpec, reference_frames_for_gen
from inbetween_copilot.signals.motion import gap_score
from inbetween_copilot.signals.regime import classify, scene_cut


def build_regime_classifier(*, tau_hold: float, tau_snap: float):
    def regime_fn(a, b) -> str:
        return classify(
            [gap_score(a, b)],
            tau_hold=tau_hold,
            tau_snap=tau_snap,
            has_cut=scene_cut(a, b),
        )

    return regime_fn


def build_interpolator(rife_engine: Callable):
    def interp_fn(route, a, b) -> list:
        if route in ("hold", "snap_preserve"):
            return [a, a, b]
        return rife_engine(a, b)

    return interp_fn


def build_generator(anisora_gen: Callable, spec: "CharacterSpec | None"):
    references = reference_frames_for_gen(spec)

    def gen_fn(a: Any, middle: Any, b: Any) -> list:
        return anisora_gen(a, middle, b, references=references)

    return gen_fn
