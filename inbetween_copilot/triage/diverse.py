"""Compatibility facade for the benchmark-specific diverse triage adapter."""
from inbetween_copilot.infrastructure.benchmark_triage import (
    BASE_AUC,
    TAU_SOFT,
    channel_su,
    fit_calibrator,
    gate_clip,
    load_calibrator,
    save_calibrator,
    to_channels,
)

__all__ = [
    "BASE_AUC", "TAU_SOFT", "channel_su", "fit_calibrator", "gate_clip",
    "load_calibrator", "save_calibrator", "to_channels",
]
