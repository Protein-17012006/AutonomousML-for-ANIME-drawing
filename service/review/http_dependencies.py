"""Injected HTTP-facing ports for review and draw-key routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class ReviewHttpRuntime:
    review_for: Callable
    load_image: Callable
    admission_for: Callable
    publish_review: Callable


def get_review_http_runtime(request: Request) -> ReviewHttpRuntime:
    runtime = getattr(request.app.state, "review_http_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="review runtime is not configured")
    return runtime
