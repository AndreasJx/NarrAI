import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import Base, engine
from .routers import (
    admin,
    approvals,
    auth,
    autopilot,
    connections,
    generation,
    media,
    metrics,
    projects,
    publications,
    renders,
    uploads,
)
from .storage import get_storage

logger = logging.getLogger("narra.api")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    try:
        get_storage().ensure_bucket()
    except Exception as exc:  # noqa: BLE001 - storage may start after the API
        logger.warning("Storage bucket check failed: %s", exc)
    yield


app = FastAPI(title="Narra API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


for module in (
    auth,
    admin,
    projects,
    generation,
    media,
    approvals,
    renders,
    uploads,
    connections,
    publications,
    metrics,
    autopilot,
):
    app.include_router(module.router, prefix="/api/v1")
