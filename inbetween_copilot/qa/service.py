"""Strategy objects for the two supported perception policies."""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.qa.perception import perceive, perceive_calibrated


@dataclass(frozen=True)
class BinaryPerception:
    vlm_fn: object
    softness_fn: object
    holdfix_fn: object = None
    tau_soft: float = 0.15

    def __call__(self, frames):
        return perceive(
            frames,
            vlm_fn=self.vlm_fn,
            softness_fn=self.softness_fn,
            holdfix_fn=self.holdfix_fn,
            tau_soft=self.tau_soft,
        )


@dataclass(frozen=True)
class CalibratedPerception:
    channel_fns: object
    base_auc: object
    calibrator: object
    transforms: object = None
    k: int = 4
    lam: float = 0.5
    stillness_fn: object = None
    tau_still: float = 0.6
    source_motion_fn: object = None
    tau_motion: float = 0.017

    def __call__(self, frames):
        return perceive_calibrated(
            frames,
            channel_fns=self.channel_fns,
            base_auc=self.base_auc,
            calibrator=self.calibrator,
            transforms=self.transforms,
            k=self.k,
            lam=self.lam,
            stillness_fn=self.stillness_fn,
            tau_still=self.tau_still,
            source_motion_fn=self.source_motion_fn,
            tau_motion=self.tau_motion,
        )
