"""FastAPI adapter for the mask-guided image-edit tool."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image

from service.core.errors import (
    ImageEditUnavailable,
    InvalidImageEdit,
    RuntimeBusy,
    UnknownImageEditModel,
)
from service.image_edit.http_dependencies import (
    ImageEditHttpRuntime,
    get_image_edit_http_runtime,
)


router = APIRouter()


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
