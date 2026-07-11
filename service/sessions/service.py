"""Framework-independent session application service.

The service owns the run use case.  FastAPI/SSE is an inbound adapter and the
renderer, publisher, engine and repository are outbound ports supplied by the
composition layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from service.sessions.repository import SessionRepository


@dataclass(frozen=True)
class SessionWorkflowAdapters:
    run_pipeline: Callable
    save_pair_mid: Callable
    explain_pairs: Callable
    region_box: Callable
    annotate_pairs: Callable
    assemble_frames: Callable
    build_montage: Callable
    build_report: Callable
    build_video: Callable
    build_pair_frames: Callable
    build_key_frames: Callable
    publish_session: Callable


@dataclass
class SessionOutcome:
    result: Any
    artifact_urls: dict
    explanations: dict
    pair_mids: dict
    key_urls: dict
    sampling: dict


class RunSession:
    def __init__(self, repository: SessionRepository, adapters: SessionWorkflowAdapters):
        self.repository = repository
        self.adapters = adapters

    def execute(self, sid: int, session_dir: str, key_arrays: list, eng, cfg,
                *, sampling: dict | None, emit_pair: Callable) -> SessionOutcome:
        a = self.adapters

        def on_pair(pair):
            mid_fn = a.save_pair_mid(pair, session_dir)
            mid_url = f"/session/{sid}/{mid_fn}" if mid_fn else None
            emit_pair(pair, mid_url)

        result = a.run_pipeline(key_arrays, eng, on_pair=on_pair)
        explanations = (
            a.explain_pairs(result, vlm_struct_fn=eng.vlm_struct_fn,
                            softness_fn=eng.softness_fn)
            if eng.vlm_struct_fn is not None else {}
        )

        regions = {}
        if explanations and key_arrays:
            height, width = key_arrays[0].shape[:2]
            for index, explanation in explanations.items():
                pixel_box = a.region_box(explanation["region"], width, height)
                regions[index] = pixel_box
                if pixel_box and width and height:
                    x0, y0, x1, y1 = pixel_box
                    explanation["box"] = [
                        x0 / width, y0 / height,
                        (x1 - x0) / width, (y1 - y0) / height,
                    ]

        for index, filename in a.annotate_pairs(
                result, explanations, session_dir).items():
            explanations[index]["annotated_url"] = f"/session/{sid}/{filename}"

        mid_engine = eng.rife_engine
        frames = a.assemble_frames(
            result, factor=cfg.smoothness, mid_engine=mid_engine)
        duration = len(frames) / cfg.fps

        a.build_montage(result, key_arrays, session_dir, regions=regions or None)
        a.build_report(
            result, session_dir, cadence_fps=cfg.cadence_fps,
            smoothness=cfg.smoothness, output_fps=cfg.fps, duration=duration,
        )
        a.build_video(
            result, session_dir, fps=cfg.fps, factor=cfg.smoothness,
            mid_engine=mid_engine, frames=frames,
        )
        pair_files = a.build_pair_frames(result, session_dir)
        key_files = a.build_key_frames(key_arrays, session_dir)

        self.repository.save_state(sid, {
            "keys": key_arrays,
            "eng": eng,
            "cfg": cfg,
            "result": result,
            "rev": 0,
            "explanations": explanations,
            "qa_degraded": bool(eng.vlm_status.get("degraded")),
        })

        pair_mids = {
            str(index): f"/session/{sid}/{filename}"
            for index, filename in pair_files.items()
        }
        key_urls = {
            str(index): f"/session/{sid}/{filename}"
            for index, filename in key_files.items()
        }
        artifact_urls = {
            "montage": f"/session/{sid}/montage.png",
            "report": f"/session/{sid}/report.md",
            "video": f"/session/{sid}/reconstructed.mp4",
        }
        sampling_payload = dict(sampling or {})
        sampling_payload.update({
            "cadence_fps": cfg.cadence_fps,
            "smoothness": cfg.smoothness,
            "output_fps": cfg.fps,
            "duration": round(duration, 3),
        })
        return SessionOutcome(
            result=result,
            artifact_urls=artifact_urls,
            explanations=explanations,
            pair_mids=pair_mids,
            key_urls=key_urls,
            sampling=sampling_payload,
        )

    def publish(self, sid: int, session_dir: str, result) -> dict:
        return self.adapters.publish_session(sid, session_dir, result) or {}
