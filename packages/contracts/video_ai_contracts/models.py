from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ApprovalGate(StrEnum):
    SCRIPT = "script"
    RENDER = "render"
    PUBLISH = "publish"


class Platform(StrEnum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    LOCAL = "local"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    PROCESSING = "processing"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class GenerationResult(BaseModel):
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_cents: int = 0


class ShotSpec(BaseModel):
    duration: float
    media_path: str | None = None
    media_kind: str | None = None
    effect: str = "zoom_in"
    clip_start: float = 0
    role: str = "broll"
    asset_id: int | None = None


class SceneSpec(BaseModel):
    position: int
    narration: str
    duration_seconds: float = 5
    media_path: str | None = None
    media_kind: str | None = None
    shots: list[ShotSpec] = Field(default_factory=list)


class RenderRequest(BaseModel):
    render_id: int
    script: str
    output_dir: str
    scenes: list[SceneSpec] = Field(default_factory=list)
    voice: str | None = None


class Artifact(BaseModel):
    uri: str
    kind: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublishRequest(BaseModel):
    title: str
    artifact_uri: str
    idempotency_key: str
    description: str = ""


class PublishResult(BaseModel):
    external_id: str
    url: str | None = None
    simulated: bool = True
