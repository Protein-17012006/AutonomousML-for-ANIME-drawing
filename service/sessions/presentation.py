"""Pure mapping from renderer filenames to one session-facing artifact view."""
from __future__ import annotations

import copy
from dataclasses import dataclass


@dataclass(frozen=True)
class RenderMetadata:
    artifact_urls: dict
    explanations: dict
    pair_mids: dict
    key_urls: dict
    sampling: dict
    qa_degraded: bool
    csq: dict | None


def build_render_metadata(
    sid: int,
    rendered,
    cfg,
    eng,
    *,
    base_sampling: dict | None,
    revision: int = 0,
) -> RenderMetadata:
    """Build URLs and sampling badges identically for initial and review runs."""
    suffix = f"?r={revision}" if revision else ""
    explanations = copy.deepcopy(rendered.explanations)
    for pair_index, filename in rendered.annotated_files.items():
        explanations[pair_index]["annotated_url"] = (
            f"/session/{sid}/{filename}{suffix}"
        )
    pair_mids = {
        str(pair_index): f"/session/{sid}/{filename}{suffix}"
        for pair_index, filename in rendered.pair_files.items()
    }
    key_urls = {
        str(key_index): f"/session/{sid}/{filename}{suffix}"
        for key_index, filename in rendered.key_files.items()
    }
    sampling = dict(base_sampling or {})
    sampling.update({
        "cadence_fps": cfg.cadence_fps,
        "smoothness": cfg.smoothness,
        "output_fps": cfg.fps,
        "duration": round(rendered.duration, 3),
        "interpolator": cfg.interpolator,
    })
    return RenderMetadata(
        artifact_urls={
            "montage": f"/session/{sid}/montage.png{suffix}",
            "report": f"/session/{sid}/report.md{suffix}",
            "video": f"/session/{sid}/reconstructed.mp4{suffix}",
        },
        explanations=explanations,
        pair_mids=pair_mids,
        key_urls=key_urls,
        sampling=sampling,
        qa_degraded=bool(eng.vlm_status.get("degraded")),
        csq=eng.csq_calibrator,
    )
