"""Concrete wiring for the mask-guided image-edit tool."""
from __future__ import annotations

from service.core.config import ImageEditSettings
from service.image_edit.http_dependencies import ImageEditHttpRuntime
from service.image_edit.ingest import load_mask_upload
from service.image_edit.service import edit_image
from service.image_edit.session_repair import validate_repair_request
from service.infrastructure.admission import engine_admission
from service.infrastructure.image_edit_client import (
    make_worker_editor,
    make_worker_span_editor,
)
from service.media.ingest import load_image_upload


def build_image_edit_http_runtime() -> ImageEditHttpRuntime:
    def run(image, mask, *, model: str | None, seed: int):
        settings = ImageEditSettings.from_env()
        selected = model or settings.default_model
        editor = make_worker_editor(
            settings.worker_url,
            settings.timeout_seconds,
        )
        return edit_image(
            image,
            mask,
            model=selected,
            seed=seed,
            editor_fn=editor,
        )

    def span_edit(frames, masks, *, model, seed, refinement_passes):
        settings = ImageEditSettings.from_env()
        editor = make_worker_span_editor(
            settings.worker_url, settings.timeout_seconds)
        return editor(
            frames, masks, model=model or settings.default_model, seed=seed,
            refinement_passes=refinement_passes)

    return ImageEditHttpRuntime(
        load_image=load_image_upload,
        load_mask=load_mask_upload,
        edit_image=run,
        admission_for=engine_admission,
        span_editor=span_edit,
        validate_repair=validate_repair_request,
    )
