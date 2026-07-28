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


def get_image_edit_http_runtime(request: Request) -> ImageEditHttpRuntime:
    return request.app.state.image_edit_http_runtime
