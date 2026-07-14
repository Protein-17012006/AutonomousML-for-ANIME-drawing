"""Small helpers shared by HTTP adapters."""
from __future__ import annotations

from typing import TypeVar

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError


ModelT = TypeVar("ModelT", bound=BaseModel)


def model_or_422(model: type[ModelT], /, **values) -> ModelT:
    """Build a Pydantic model and expose validation failures as HTTP 422."""
    try:
        return model(**values)
    except ValidationError as exc:
        detail = "; ".join(error["msg"] for error in exc.errors()) or str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc
