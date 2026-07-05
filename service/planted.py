"""Planted-error DEMO sessions (labeled, honest): load a (key A, stored bad mid, key B)
trio from a frozen benchmark suite and run the REAL production QA/annotate path over it —
only the interpolation step is replaced by the stored mid. Exists because the live path
yields no natural flags (gate refuses ghost-prone pairs; probes n=9 2026-07-03 + n=40
2026-07-04), so demonstrating the flag→annotate surface needs a planted mid. Every event
carries `planted` metadata; the UI must label it as a planted demo.
"""
from __future__ import annotations

import pathlib

import numpy as np

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SUITES = _ROOT / "benchmark" / "suites"

# Curated trios across DIVERSE error classes (not just scene transitions):
# frame indices follow each suite's layout (suite_*_rife clips are interleaved:
# even = source keys, odd = stored RIFE mids; suite_motion clips are generated 16f).
# NOTE selection principle (E2E-verified 2026-07-05): planted mids must be GROSS errors —
# faint small-gap ghosts / blends between near-identical keys / flicker pops honestly read
# clean to CSQ (they ARE the documented weak classes, rare-by-nature). Every case below was
# verified to FLAG through the real box engines before shipping.
CASES = [
    {"id": "ghost_fight", "suite": "suite_rife", "clip": "f031",
     "a": 8, "mid": 9, "b": 10, "planted_type": "warp_melt",
     "title": "Character double-image ghost (fight scene)"},
    {"id": "ghost_slide", "suite": "suite_rife", "clip": "f007",
     "a": 8, "mid": 9, "b": 10, "planted_type": "warp_melt",
     "title": "Sliding figure double-image ghost"},
    {"id": "morph_smallgap", "suite": "suite_smallgap", "clip": "w0062_rife",
     "a": 2, "mid": 3, "b": 4, "planted_type": "morph",
     "title": "Small-gap morph (RIFE, real fail)"},
    {"id": "drift", "suite": "suite_motion", "clip": "c011",
     "a": 7, "mid": 8, "b": 9, "planted_type": "identity_drift",
     "title": "Identity drift"},
    {"id": "ghost_transition", "suite": "suite_rife", "clip": "f002",
     "a": 8, "mid": 9, "b": 10, "planted_type": "warp_melt",
     "title": "Transition ghost (classic)"},
]


def list_cases() -> list[dict]:
    """Public case list for the UI (id + label only — paths stay server-side)."""
    return [{"id": c["id"], "title": c["title"], "planted_type": c["planted_type"]}
            for c in CASES]


def _frame(suite: str, clip: str, idx: int) -> np.ndarray:
    from PIL import Image
    p = _SUITES / suite / "clips" / clip / f"{idx:04d}.png"
    if not p.exists():
        raise FileNotFoundError(f"planted case frame missing: {p}")
    return np.array(Image.open(p).convert("RGB"), dtype=np.uint8)


def load_case(case_id: str):
    """Return (keys=[A, B], mid, meta) for a case id; KeyError if unknown."""
    c = next((c for c in CASES if c["id"] == case_id), None)
    if c is None:
        raise KeyError(case_id)
    a = _frame(c["suite"], c["clip"], c["a"])
    mid = _frame(c["suite"], c["clip"], c["mid"])
    b = _frame(c["suite"], c["clip"], c["b"])
    meta = {"planted": c["id"], "planted_type": c["planted_type"],
            "planted_src": f"{c['suite']}/{c['clip']}"}
    return [a, b], mid, meta


def planted_overrides(mid: np.ndarray) -> dict:
    """Engine overrides that plant `mid` as the pair's in-between while keeping the
    ENTIRE QA/perception/annotate path production-real. gap/regime are pinned so the
    gate cannot refuse the pair (that refusal is exactly what a planted demo bypasses,
    by design and clearly labeled)."""
    return {
        "gap_fn": lambda a, b: 0.001,                # interpolable (TAU_GATE = 0.017)
        "regime_fn": lambda a, b: "small",           # route = rife-style fill
        "interp_fn": lambda route, a, b: [a, mid, b],   # window shape matches the real
                                                        # rife_engine: [a, mid, b]
    }
