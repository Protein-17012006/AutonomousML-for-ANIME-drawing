"""Finished-session review and draw-key correction application service."""
from __future__ import annotations

import io
import pathlib

import numpy as np
from PIL import Image

from service.core.errors import InvalidGapIndex, SessionNotFound
from service.media.annotate import annotate_explained_pairs
from service.media.artifacts import build_montage, build_pair_frames, build_report, build_video
from service.media.explain import explain_pairs, region_box
from service.sessions.repository import SessionRepository
from service.sessions.runner import recompute_result, run_session
from service.sessions.schemas import PairEvent, ResultEvent


class ReviewSession:
    def __init__(self, repository: SessionRepository):
        self.repository = repository

    def state(self, sid: int) -> dict:
        state = self.repository.state_for(sid)
        if state is None:
            raise SessionNotFound(f"session {sid} was not found or has expired")
        return state

    def artifact_dir(self, sid: int) -> pathlib.Path:
        path = self.repository.path_for(sid)
        if path is None:
            raise SessionNotFound(f"session {sid} was not found or has expired")
        return pathlib.Path(path).resolve()

    def add_key(self, sid: int, index: int, image_bytes: bytes) -> dict:
        state = self.state(sid)
        keys, eng, cfg, result = (
            state["keys"], state["eng"], state["cfg"], state["result"],
        )
        if not 0 <= index < len(keys) - 1:
            raise InvalidGapIndex(f"gap index {index} out of range")

        drawn = np.array(
            Image.open(io.BytesIO(image_bytes)).convert("RGB"), dtype=np.uint8)
        left, right = keys[index], keys[index + 1]
        sub_pairs = list(run_session([left, drawn, right], eng).pairs)

        new_keys = keys[:index + 1] + [drawn] + keys[index + 1:]
        new_pairs = []
        for pair in result.pairs:
            if pair.index < index:
                new_pairs.append(pair)
            elif pair.index == index:
                sub_pairs[0].index = index
                if len(sub_pairs) > 1:
                    sub_pairs[1].index = index + 1
                new_pairs.extend(sub_pairs)
            else:
                pair.index += 1
                new_pairs.append(pair)
        new_result = recompute_result(new_pairs)
        session_dir = str(self.artifact_dir(sid))

        explanations = (
            explain_pairs(
                new_result, vlm_struct_fn=eng.vlm_struct_fn,
                softness_fn=eng.softness_fn,
            ) if eng.vlm_struct_fn is not None else {}
        )
        regions = {}
        if explanations:
            height, width = new_keys[0].shape[:2]
            for pair_index, explanation in explanations.items():
                pixel_box = region_box(explanation["region"], width, height)
                regions[pair_index] = pixel_box
                if pixel_box and width and height:
                    x0, y0, x1, y1 = pixel_box
                    explanation["box"] = [
                        x0 / width, y0 / height,
                        (x1 - x0) / width, (y1 - y0) / height,
                    ]

        annotated = annotate_explained_pairs(
            new_result, explanations, session_dir)
        build_montage(new_result, new_keys, session_dir, regions=regions or None)
        build_report(new_result, session_dir)
        build_video(
            new_result, session_dir, fps=cfg.fps, factor=cfg.smoothness,
            mid_engine=eng.rife_engine,
        )
        pair_files = build_pair_frames(new_result, session_dir)

        state["keys"] = new_keys
        state["result"] = new_result
        state["explanations"] = explanations
        state["qa_degraded"] = bool(eng.vlm_status.get("degraded"))
        state["rev"] = state.get("rev", 0) + 1
        self.repository.save_state(sid, state)

        cache_bust = f"?r={state['rev']}"
        for pair_index, filename in annotated.items():
            explanations[pair_index]["annotated_url"] = (
                f"/session/{sid}/{filename}{cache_bust}")
        pair_mids = {
            str(pair_index): f"/session/{sid}/{filename}{cache_bust}"
            for pair_index, filename in pair_files.items()
        }
        artifact_urls = {
            "montage": f"/session/{sid}/montage.png{cache_bust}",
            "report": f"/session/{sid}/report.md{cache_bust}",
            "video": f"/session/{sid}/reconstructed.mp4{cache_bust}",
        }
        pairs_payload = [
            PairEvent.from_pair(
                pair, mid_url=pair_mids.get(str(pair.index))).model_dump()
            for pair in new_result.pairs
        ]
        result_payload = ResultEvent.from_result(
            new_result,
            artifact_urls,
            explanations=explanations,
            pair_mids=pair_mids,
            csq=eng.csq_calibrator,
        ).model_dump()
        return {"pairs": pairs_payload, "result": result_payload}
