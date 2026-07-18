"""Model-free FastAPI entrypoint for local authentication testing.

Run with:
    uvicorn service.auth_dev_app:app --reload --env-file service/.env.local

This intentionally does not import ``service.app`` or the co-pilot model stack.
"""
from __future__ import annotations

from fastapi import FastAPI

from service.auth_api import router as auth_router
from service.core.config import AuthSettings


# Fail at process startup when the local auth environment is incomplete or unsafe.
AuthSettings.from_env()

app = FastAPI(title="In-Between Co-pilot local auth")
app.include_router(auth_router)


@app.get("/healthz", tags=["operations"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
