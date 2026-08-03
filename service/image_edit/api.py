"""FastAPI adapter for the mask-guided image-edit tool."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from service.core.auth import request_user_sub
from service.core.errors import (
    ImageEditUnavailable,
    InvalidImageEdit,
    RuntimeBusy,
    SessionNotFound,
    UnknownImageEditModel,
)
from service.image_edit.http_dependencies import (
    ImageEditHttpRuntime,
    get_image_edit_http_runtime,
)
from service.review.api import (
    _release_review_job,
    _reserve_review_job,
    _review_stream,
)
from service.review.http_dependencies import (
    ReviewHttpRuntime,
    get_review_http_runtime,
)
from service.sessions.http_dependencies import get_session_repository
from service.sessions.repository import SessionRepository


router = APIRouter()


class RepairMask(BaseModel):
    frame: int
    png: str


class RepairReq(BaseModel):
    masks: list[RepairMask]
    refinement_passes: int = 1


@router.post("/tools/image-edit")
def post_image_edit(
    image: UploadFile = File(...),
    mask: UploadFile = File(...),
    model: str | None = Form(None),
    seed: int = Form(2026),
    runtime: ImageEditHttpRuntime = Depends(get_image_edit_http_runtime),
):
    lease = None
    try:
        source = runtime.load_image(image)
        painted_mask = runtime.load_mask(mask)
        lease = runtime.admission_for("box").acquire()
        result = runtime.edit_image(
            source,
            painted_mask,
            model=model,
            seed=seed,
        )
        buffer = io.BytesIO()
        Image.fromarray(result.image, mode="RGB").save(buffer, format="PNG")
        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={
                "X-Image-Edit-Model": result.model,
                "X-Image-Edit-Seed": str(result.seed),
                "X-Image-Edit-Mask-Fraction": f"{result.mask_fraction:.6f}",
            },
        )
    except (InvalidImageEdit, UnknownImageEditModel) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeBusy as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ImageEditUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if lease is not None:
            lease.release()


@router.post("/session/{sid}/pair/{index}/repair")
def post_pair_repair(
    sid: int,
    index: int,
    request: Request,
    payload: RepairReq,
    sessions: SessionRepository = Depends(get_session_repository),
    runtime: ImageEditHttpRuntime = Depends(get_image_edit_http_runtime),
    review_runtime: ReviewHttpRuntime = Depends(get_review_http_runtime),
):
    span_editor = getattr(runtime, "span_editor", None)
    if span_editor is None:
        raise HTTPException(
            status_code=503, detail="in-session repair is not configured")
    try:
        state = review_runtime.review_for(sessions).state(sid)
    except SessionNotFound as exc:
        raise HTTPException(
            status_code=404, detail="Unknown or expired session") from exc

    # Refuse before the GPU is touched, and say which rule fired. The
    # transaction re-validates against the state it actually locks.
    try:
        runtime.validate_repair(
            state, index, [mask.model_dump() for mask in payload.masks],
            payload.refinement_passes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    pid = state.get("published_pid")
    if not isinstance(pid, str) or not pid:
        raise HTTPException(status_code=409, detail="Session is still being saved")
    workspace_input = state.get("workspace_input") or {}
    owner_sub = request_user_sub(request)
    masks = [mask.model_dump() for mask in payload.masks]
    # The SAME reservation review uses: a repair must not run beside a re-run or
    # a verdict batch on one session, and two tabs must not race two revisions.
    _reserve_review_job(sid, sessions)

    def job(progress):
        try:
            lease = review_runtime.admission_for(state["cfg"].engines).acquire()
            try:
                progress("Repairing painted frames")
                outcome = review_runtime.review_for(sessions).repair_pair(
                    sid, index, masks, span_editor=span_editor,
                    refinement_passes=payload.refinement_passes)
                progress("Saving repair revision")
                published = review_runtime.publish_review(
                    sid, review_runtime.review_for(sessions).artifact_dir(sid),
                    outcome, owner_sub=owner_sub, pid=pid,
                    workspace_input=workspace_input)
                if not published.get("published"):
                    raise RuntimeError(
                        published.get("error") or "Could not save repair revision")
                return outcome
            finally:
                lease.release()
        finally:
            _release_review_job(sid, sessions)

    return _review_stream(job)
