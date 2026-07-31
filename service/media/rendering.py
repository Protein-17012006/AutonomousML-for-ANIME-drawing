"""Render the complete, internally consistent artifact set for one session."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from service.media import artifacts
from service.media.annotate import annotate_explained_pairs
from service.media.explain import explain_pairs, region_box


@dataclass(frozen=True)
class RenderedSessionArtifacts:
    """Files and metadata produced by :func:`render_session_artifacts`."""

    explanations: dict
    annotated_files: dict[int, str]
    pair_files: dict[int, str]
    key_files: dict[int, str]
    frame_count: int
    duration: float
    compare_file: "str | None" = None   # compare.mp4 basename; None when nothing filled


def render_session_artifacts(
    result: Any,
    keys: list,
    out_dir: str,
    *,
    cadence_fps: int,
    smoothness: int,
    output_fps: int,
    mid_engine: Callable | None = None,
    vlm_struct_fn: Callable | None = None,
    softness_fn: Callable | None = None,
    gt_frames: list | None = None,
) -> RenderedSessionArtifacts:
    """Write every final-session artifact from one shared render calculation.

    The renderer deliberately accepts primitive values and callable ports instead
    of importing the session config or engine bundle.  This keeps media rendering
    reusable by both the initial-run and finished-review application services.
    """
    explanations = (
        explain_pairs(
            result,
            vlm_struct_fn=vlm_struct_fn,
            softness_fn=softness_fn,
        )
        if vlm_struct_fn is not None
        else {}
    )

    regions = {}
    if explanations and keys:
        height, width = keys[0].shape[:2]
        for pair_index, explanation in explanations.items():
            pixel_box = region_box(explanation["region"], width, height)
            regions[pair_index] = pixel_box
            if pixel_box and width and height:
                x0, y0, x1, y1 = pixel_box
                explanation["box"] = [
                    x0 / width,
                    y0 / height,
                    (x1 - x0) / width,
                    (y1 - y0) / height,
                ]

    annotated_files = annotate_explained_pairs(result, explanations, out_dir)
    frames = artifacts._assemble_frames(
        result, factor=smoothness, mid_engine=mid_engine)
    duration = len(frames) / output_fps

    artifacts.build_montage(
        result, keys, out_dir, regions=regions or None)
    artifacts.build_report(
        result,
        out_dir,
        cadence_fps=cadence_fps,
        smoothness=smoothness,
        output_fps=output_fps,
        duration=duration,
    )
    artifacts.build_video(
        result,
        out_dir,
        fps=output_fps,
        factor=smoothness,
        mid_engine=mid_engine,
        frames=frames,
    )
    pair_files = artifacts.build_pair_frames(result, out_dir)
    key_files = artifacts.build_key_frames(keys, out_dir)
    # box-style side-by-side ORIGINAL|RECON. cadence*2 = the restored full rate
    # (on-2s 12 -> 24fps, the box compare_video rate) — NOT output_fps, which
    # differs at smoothness 1.
    compare_file = artifacts.build_compare(
        result, keys, out_dir, fps=cadence_fps * 2, gt_frames=gt_frames)

    return RenderedSessionArtifacts(
        explanations=explanations,
        annotated_files=annotated_files,
        pair_files=pair_files,
        key_files=key_files,
        frame_count=len(frames),
        duration=duration,
        compare_file=compare_file,
    )
