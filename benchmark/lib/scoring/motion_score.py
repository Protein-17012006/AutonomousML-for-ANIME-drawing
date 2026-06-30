"""Score one motion arm's per-clip verdicts against the frozen manifest.

The unit is a CLIP, binary:
  - role "error" flagged has_motion_error=True  -> caught
  - role "error" flagged False                  -> missed
  - role "clean" flagged True                   -> false positive
  - role "clean" flagged False                  -> true negative
  - has_motion_error is None / clip absent       -> abstain (excluded from counts)
"""
from __future__ import annotations

from benchmark.lib.manifest.motion_manifest import MotionManifest


def score_motion(verdicts_by_clip: dict[str, dict],
                 manifest: MotionManifest) -> dict:
    caught = missed = false = true_neg = abstain = 0
    for clip in manifest.clips:
        v = verdicts_by_clip.get(clip["id"])
        flag = v.get("has_motion_error") if v else None
        if flag is None:
            abstain += 1
            continue
        if clip["role"] == "error":
            if flag:
                caught += 1
            else:
                missed += 1
        else:  # clean
            if flag:
                false += 1
            else:
                true_neg += 1
    n_error = caught + missed
    n_clean = false + true_neg
    recall = caught / n_error if n_error else 0.0
    precision = caught / (caught + false) if (caught + false) else 0.0
    return {"caught": caught, "missed": missed, "false": false,
            "true_neg": true_neg, "abstain": abstain,
            "n_error": n_error, "n_clean": n_clean,
            "precision": round(precision, 3), "recall": round(recall, 3)}


def score_by_regime(verdicts_by_clip: dict[str, dict],
                    manifest: MotionManifest) -> dict[str, dict]:
    """Group clips by their manifest 'regime' and score each group with
    score_motion. Clips with no 'regime' key fall into 'all', so suites that
    don't carry regime (suite_rife, suite_motion) yield a single 'all' group
    equal to the overall score. Does not modify score_motion."""
    regimes = sorted({c.get("regime", "all") for c in manifest.clips})
    out: dict[str, dict] = {}
    for r in regimes:
        sub = MotionManifest(
            version=manifest.version, source=manifest.source,
            generator=manifest.generator,
            clips=[c for c in manifest.clips if c.get("regime", "all") == r],
            frozen=manifest.frozen)
        out[r] = score_motion(verdicts_by_clip, sub)
    return out
