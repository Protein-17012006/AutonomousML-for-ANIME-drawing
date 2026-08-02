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
from service.image_edit.session_repair import (
    qa_blast_radius,
    repair_frames,
    rerun_qa,
    validate_repair_request,
)
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
            return self._add_keys_locked(sid, [(index, image)])

    def add_keys(self, sid: int, keys: list[tuple[int, "bytes | np.ndarray"]],
                 *, on_pair: Callable | None = None,
                 cancelled: Callable[[], bool] | None = None) -> SessionOutcome:
        """Apply one complete artist key batch as one live-state revision.

        The caller supplies original gap indices.  We insert descending so an
        earlier insertion cannot invalidate a later submitted index.
        """
        with self.repository.session_transaction(sid):
            return self._add_keys_locked(
                sid, keys, on_pair=on_pair, cancelled=cancelled)

    def _add_keys_locked(self, sid: int, submitted: list[tuple[int, "bytes | np.ndarray"]],
                         *, on_pair: Callable | None = None,
                         cancelled: Callable[[], bool] | None = None) -> SessionOutcome:
        state = self.state(sid)
        keys, eng, cfg, result = (
            state["keys"], state["eng"], state["cfg"], state["result"],
        )
        expected = {pair.index for pair in result.pairs if pair.action == "needs_key"}
        supplied = [index for index, _ in submitted]
        if not submitted or len(supplied) != len(set(supplied)) or set(supplied) != expected:
            raise InvalidGapIndex("submit exactly one drawn key for every current needs-key pair")

        decoded: dict[int, np.ndarray] = {}
        for index, image in submitted:
            if not 0 <= index < len(keys) - 1:
                raise InvalidGapIndex(f"gap index {index} out of range")
            drawn = (np.asarray(image, dtype=np.uint8) if isinstance(image, np.ndarray)
                     else np.array(Image.open(io.BytesIO(image)).convert("RGB"), dtype=np.uint8))
            if drawn.shape != np.asarray(keys[index]).shape:
                expected_h, expected_w = np.asarray(keys[index]).shape[:2]
                got_h, got_w = drawn.shape[:2]
                raise InvalidKeyImage(
                    f"drawn key for gap {index} must be {expected_w}x{expected_h}; got {got_w}x{got_h}")
            decoded[index] = drawn

        new_keys = list(keys)
        for index in sorted(decoded, reverse=True):
            new_keys.insert(index + 1, decoded[index])
        # The drawn key splits gap `index`; its stored middle-GT frame no longer
        # aligns with either sub-gap, so both fall back to held-key (None) while
        # every other gap keeps its real GT for the compare artifact.
        old_gt = state.get("gt_frames")
        new_gt = list(old_gt) if old_gt else old_gt
        if new_gt is not None:
            for index in sorted(decoded, reverse=True):
                new_gt[index:index + 1] = [None, None]
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
            new_result = run_session(new_keys, eng, cfg=cfg, on_pair=on_pair)
            if cancelled and cancelled():
                raise RuntimeError("Review submission was cancelled")
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

        if cancelled and cancelled():
            shutil.rmtree(stage_path, ignore_errors=True)
            restore_vlm_status()
            raise RuntimeError("Review submission was cancelled")

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

    def repair_pair(self, sid: int, index: int, masks, *, span_editor,
                    model: str = "diffueraser", seed: int = 2026,
                    refinement_passes: int = 1,
                    cancelled: Callable[[], bool] | None = None) -> SessionOutcome:
        """Repair one pair's painted frames and commit it as one revision.

        Shaped like :meth:`apply_verdicts` on purpose: repaired pixels, the
        re-run calibrated verdict and the cleared ``artist_verdict`` install
        together or not at all. Publishing to the durable store without this
        local commit would leave a reopened session showing the old frames.
        """
        with self.repository.session_transaction(sid):
            if cancelled and cancelled():
                raise RuntimeError("Repair was cancelled")
            state = self.state(sid)
            decoded = validate_repair_request(
                state, index, masks, refinement_passes)

            # Everything expensive happens before anything is installed: the
            # GPU repair, then QA. A failure in either leaves live state and the
            # artifact directory exactly as they were.
            frames = repair_frames(
                state, index, decoded, span_editor=span_editor,
                model=model, seed=seed, refinement_passes=refinement_passes,
            )

            result = copy.deepcopy(state["result"])
            by_index = {pair.index: pair for pair in result.pairs}
            by_index[index].frames = frames
            by_index[index].artist_verdict = None

            eng, cfg = state["eng"], state["cfg"]
            affected = qa_blast_radius(
                result.pairs, index, qa_window=getattr(eng, "qa_window", False))
            verdicts = rerun_qa(
                result.pairs, affected,
                qa_fn=eng.qa_fn, softness_fn=eng.softness_fn,
                qa3_fn=getattr(eng, "qa3_fn", None), tau_soft=cfg.tau_soft,
                qa_window=getattr(eng, "qa_window", False),
            )
            for pair_index, verdict in verdicts.items():
                by_index[pair_index].qa = verdict
            new_result = recompute_result(result.pairs)

            session_path = self.artifact_dir(sid)
            stage_path = pathlib.Path(tempfile.mkdtemp(
                prefix=f".{session_path.name}.repair-", dir=session_path.parent))
            try:
                rendered = self.render_artifacts(
                    new_result, state["keys"], str(stage_path),
                    cadence_fps=cfg.cadence_fps, smoothness=cfg.smoothness,
                    output_fps=cfg.fps, mid_engine=eng.rife_engine,
                    vlm_struct_fn=eng.vlm_struct_fn, softness_fn=eng.softness_fn,
                    gt_frames=state.get("gt_frames"))
                revision = state.get("rev", 0) + 1
                metadata = build_render_metadata(
                    sid, rendered, cfg, eng, base_sampling=state.get("sampling"),
                    revision=revision)
                if cancelled and cancelled():
                    raise RuntimeError("Repair was cancelled")
                backup_path = session_path.with_name(
                    f".{session_path.name}.backup-{uuid.uuid4().hex}")
                session_path.rename(backup_path)
                try:
                    stage_path.rename(session_path)
                except Exception:
                    backup_path.rename(session_path)
                    raise
                try:
                    self.repository.save_state(sid, {
                        **state, "result": new_result,
                        "explanations": copy.deepcopy(metadata.explanations),
                        "qa_degraded": metadata.qa_degraded,
                        "sampling": dict(metadata.sampling), "rev": revision})
                except Exception:
                    failed_path = session_path.with_name(
                        f".{session_path.name}.failed-{uuid.uuid4().hex}")
                    session_path.rename(failed_path)
                    backup_path.rename(session_path)
                    shutil.rmtree(failed_path, ignore_errors=True)
                    raise
                shutil.rmtree(backup_path, ignore_errors=True)
            except Exception:
                shutil.rmtree(stage_path, ignore_errors=True)
                raise
            return SessionOutcome(
                new_result, sid, metadata.artifact_urls, metadata.explanations,
                metadata.pair_mids, metadata.key_urls, metadata.sampling,
                metadata.csq, metadata.qa_degraded)

    def apply_verdicts(self, sid: int, verdicts: dict[int, str],
                       *, cancelled: Callable[[], bool] | None = None) -> SessionOutcome:
        """Commit artist decisions; a rejection turns that pair into a key request."""
        with self.repository.session_transaction(sid):
            if cancelled and cancelled():
                raise RuntimeError("Review submission was cancelled")
            state = self.state(sid)
            result = copy.deepcopy(state["result"])
            by_index = {pair.index: pair for pair in result.pairs}
            for index, verdict in verdicts.items():
                pair = by_index.get(index)
                if pair is None or pair.action == "needs_key":
                    raise InvalidGapIndex(f"pair {index} cannot receive a verdict")
                pair.artist_verdict = verdict
                if verdict == "reject":
                    pair.action = "needs_key"
                    pair.frames = None
            new_result = recompute_result(result.pairs)
            # Verdicts alter the reconstructed cut too, so render and atomically
            # install a new artifact generation using the same commit boundary.
            session_path = self.artifact_dir(sid)
            stage_path = pathlib.Path(tempfile.mkdtemp(prefix=f".{session_path.name}.review-", dir=session_path.parent))
            eng, cfg = state["eng"], state["cfg"]
            try:
                rendered = self.render_artifacts(new_result, state["keys"], str(stage_path), cadence_fps=cfg.cadence_fps, smoothness=cfg.smoothness, output_fps=cfg.fps, mid_engine=eng.rife_engine, vlm_struct_fn=eng.vlm_struct_fn, softness_fn=eng.softness_fn, gt_frames=state.get("gt_frames"))
                revision = state.get("rev", 0) + 1
                metadata = build_render_metadata(sid, rendered, cfg, eng, base_sampling=state.get("sampling"), revision=revision)
                if cancelled and cancelled():
                    raise RuntimeError("Review submission was cancelled")
                backup_path = session_path.with_name(f".{session_path.name}.backup-{uuid.uuid4().hex}")
                session_path.rename(backup_path)
                stage_path.rename(session_path)
                self.repository.save_state(sid, {**state, "result": new_result, "explanations": copy.deepcopy(metadata.explanations), "qa_degraded": metadata.qa_degraded, "sampling": dict(metadata.sampling), "rev": revision})
                shutil.rmtree(backup_path, ignore_errors=True)
            except Exception:
                shutil.rmtree(stage_path, ignore_errors=True)
                raise
            return SessionOutcome(new_result, sid, metadata.artifact_urls, metadata.explanations, metadata.pair_mids, metadata.key_urls, metadata.sampling, metadata.csq, metadata.qa_degraded)
