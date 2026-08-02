"""Inbound HTTP runtime contract for image editing."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class ImageEditHttpRuntime:
    load_image: object
    load_mask: object
    edit_image: object
    admission_for: object
    # In-session repair. Optional so a deployment without a span-capable worker
    # answers 503 rather than 500, and so existing test runtimes still build.
    span_editor: object = None
    validate_repair: object = None


def get_image_edit_http_runtime(request: Request) -> ImageEditHttpRuntime:
    return request.app.state.image_edit_http_runtime
