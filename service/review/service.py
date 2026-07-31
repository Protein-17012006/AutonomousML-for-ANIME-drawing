"""Finished-session review and draw-key correction application service."""
from __future__ import annotations

import copy
import io
import pathlib
import shutil
import tempfile
import uuid
from dataclasses import replace
from typing import Callable

import numpy as np
from PIL import Image

from service.core.errors import InvalidGapIndex, InvalidKeyImage, SessionNotFound
from service.sessions.presentation import build_render_metadata
from service.sessions.repository import SessionRepository
from service.sessions.runner import recompute_result, run_session
from service.sessions.service import SessionOutcome


class ReviewSession:
    def __init__(self, repository: SessionRepository, render_artifacts: Callable):
        self.repository = repository
        self.render_artifacts = render_artifacts

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

    def add_key(self, sid: int, index: int,
                image: "bytes | np.ndarray") -> SessionOutcome:
        # Stub sessions may admit several jobs concurrently. Serialize edits of
        # the same SID so two corrections cannot both commit from one revision.
        with self.repository.session_transaction(sid):
            return self._add_key_locked(sid, index, image)

    def _add_key_locked(self, sid: int, index: int,
                        image: "bytes | np.ndarray") -> SessionOutcome:
        state = self.state(sid)
        keys, eng, cfg, result = (
            state["keys"], state["eng"], state["cfg"], state["result"],
        )
        if not 0 <= index < len(keys) - 1:
            raise InvalidGapIndex(f"gap index {index} out of range")

        drawn = (
            np.asarray(image, dtype=np.uint8)
            if isinstance(image, np.ndarray)
            else np.array(
                Image.open(io.BytesIO(image)).convert("RGB"), dtype=np.uint8)
        )
        if drawn.shape != np.asarray(keys[index]).shape:
            expected_h, expected_w = np.asarray(keys[index]).shape[:2]
            got_h, got_w = drawn.shape[:2]
            raise InvalidKeyImage(
                f"drawn key must be {expected_w}x{expected_h}; got {got_w}x{got_h}")
        new_keys = keys[:index + 1] + [drawn] + keys[index + 1:]
        # The drawn key splits gap `index`; its stored middle-GT frame no longer
        # aligns with either sub-gap, so both fall back to held-key (None) while
        # every other gap keeps its real GT for the compare artifact.
        old_gt = state.get("gt_frames")
        new_gt = (list(old_gt[:index]) + [None, None] + list(old_gt[index + 1:])
                  if old_gt else old_gt)
        vlm_status_before = copy.deepcopy(eng.vlm_status)

        def restore_vlm_status() -> None:
            # Engine closures share this dict with the persisted state. A failed
            # attempt must not leak a degraded flag into the prior generation.
            eng.vlm_status.clear()
            eng.vlm_status.update(vlm_status_before)

        # Production QA judges centered, cross-pair windows.  Inserting one key
        # changes those windows beyond the two split gaps, so a local splice is
        # not semantically equivalent to a normal run.  Keep the cheap splice
        # only for engines whose QA input is provably pair-local (the stub).
        try:
            if eng.qa_window:
                new_result = run_session(new_keys, eng, cfg=cfg)
            else:
                left, right = keys[index], keys[index + 1]
                sub_pairs = list(run_session([left, drawn, right], eng, cfg=cfg).pairs)
                new_pairs = []
                for pair in result.pairs:
                    if pair.index < index:
                        new_pairs.append(replace(pair))
                    elif pair.index == index:
                        new_pairs.extend(
                            replace(sub_pair, index=index + offset)
                            for offset, sub_pair in enumerate(sub_pairs)
                        )
                    else:
                        # Copy-on-write: never re-index the PairResult retained in
                        # the repository.  A later render failure must leave the
                        # previously published state byte-for-byte meaningful.
                        new_pairs.append(replace(pair, index=pair.index + 1))
                new_result = recompute_result(new_pairs)
        except Exception:
            restore_vlm_status()
            raise

        try:
            session_path = self.artifact_dir(sid)
            stage_path = pathlib.Path(tempfile.mkdtemp(
                prefix=f".{session_path.name}.review-", dir=session_path.parent,
            ))
        except Exception:
            restore_vlm_status()
            raise
        try:
            rendered = self.render_artifacts(
                new_result,
                new_keys,
                str(stage_path),
                cadence_fps=cfg.cadence_fps,
                smoothness=cfg.smoothness,
                output_fps=cfg.fps,
                mid_engine=eng.rife_engine,
                vlm_struct_fn=eng.vlm_struct_fn,
                softness_fn=eng.softness_fn,
                gt_frames=new_gt,
            )
            revision = state.get("rev", 0) + 1
            metadata = build_render_metadata(
                sid,
                rendered,
                cfg,
                eng,
                base_sampling=state.get("sampling"),
                revision=revision,
            )
        except Exception:
            shutil.rmtree(stage_path, ignore_errors=True)
            restore_vlm_status()
            raise

        # Install the complete staged artifact set as one directory generation.
        # Keep the old directory until state persistence succeeds so either
        # failure can roll back to the last consistent state/artifact pair.
        backup_path = session_path.with_name(
            f".{session_path.name}.backup-{uuid.uuid4().hex}")
        try:
            session_path.rename(backup_path)
            try:
                stage_path.rename(session_path)
            except Exception:
                backup_path.rename(session_path)
                raise

            new_state = {
                **state,
                "keys": new_keys,
                "result": new_result,
                "gt_frames": new_gt,
                "explanations": copy.deepcopy(metadata.explanations),
                "qa_degraded": metadata.qa_degraded,
                "sampling": dict(metadata.sampling),
                "rev": revision,
            }
            try:
                self.repository.save_state(sid, new_state)
            except Exception:
                # The staged generation is now at session_path.  Move it aside,
                # restore the prior artifacts, and let the repository error
                # propagate; the original state object was never mutated.
                failed_path = session_path.with_name(
                    f".{session_path.name}.failed-{uuid.uuid4().hex}")
                session_path.rename(failed_path)
                backup_path.rename(session_path)
                shutil.rmtree(failed_path, ignore_errors=True)
                raise
        except Exception:
            shutil.rmtree(stage_path, ignore_errors=True)
            restore_vlm_status()
            raise
        else:
            shutil.rmtree(backup_path, ignore_errors=True)

        return SessionOutcome(
            result=new_result,
            sid=sid,
            artifact_urls=metadata.artifact_urls,
            explanations=metadata.explanations,
            pair_mids=metadata.pair_mids,
            key_urls=metadata.key_urls,
            sampling=metadata.sampling,
            csq=metadata.csq,
            qa_degraded=metadata.qa_degraded,
        )
