from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
Role = Literal["owner", "editor", "viewer"]
Language = Literal["pt-BR", "en-US", "en-GB"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class LoginIn(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(ORMModel):
    id: int
    email: str
    name: str


class OrganizationOut(ORMModel):
    id: int
    name: str
    monthly_budget_cents: int
    voice: str
    voices: dict[str, str] = Field(default_factory=dict)

    @field_validator("voices", mode="before")
    @classmethod
    def default_voices(cls, value: Any) -> Any:
        return value or {}


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    monthly_budget_cents: int | None = Field(default=None, ge=0)
    voice: str | None = None


class MeOut(BaseModel):
    user: UserOut
    organization: OrganizationOut
    role: Role
    organizations: list[OrganizationOut]


class SwitchOrganization(BaseModel):
    organization_id: int


class MemberCreate(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    role: Role = "editor"
    password: str | None = Field(default=None, min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class MemberUpdate(BaseModel):
    role: Role


class MemberOut(BaseModel):
    user_id: int
    email: str
    name: str
    role: Role
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    budget_cents: int = Field(default=1000, ge=0)
    language: Language = "pt-BR"


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    budget_cents: int | None = Field(default=None, ge=0)
    language: Language | None = None


class ProjectOut(ORMModel):
    id: int
    name: str
    status: str
    budget_cents: int
    spent_cents: int
    language: str = "pt-BR"
    autopilot: bool = False
    autopilot_stage: str | None = None
    autopilot_reason: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class BriefCreate(BaseModel):
    topic: str = Field(min_length=2, max_length=500)
    audience: str = Field(default="general", max_length=500)
    objective: str = Field(default="engagement", max_length=500)
    language: Language = "pt-BR"
    constraints: dict[str, Any] = Field(default_factory=dict)


class BriefOut(ORMModel):
    id: int
    project_id: int
    topic: str
    audience: str
    objective: str
    language: str = "pt-BR"
    constraints: dict[str, Any]
    created_at: datetime


class DossierOut(ORMModel):
    id: int
    project_id: int
    language: str
    summary: str
    facts: list[dict[str, Any]]
    angles: list[str]
    hooks: list[str]
    controversies: list[str]
    video_moments: list[dict[str, Any]]
    provider: str
    cost_cents: int
    created_at: datetime


class SourceOut(ORMModel):
    id: int
    project_id: int
    title: str
    url: str | None
    summary: str
    provider: str
    created_at: datetime


class GenerationRequest(BaseModel):
    estimated_cost_cents: int = Field(default=10, ge=0)


class ScriptOut(ORMModel):
    id: int
    project_id: int
    version: int
    content: str
    estimated_cost_cents: int
    author: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ScriptUpdate(BaseModel):
    content: str = Field(min_length=2, max_length=20_000)


class SceneOut(ORMModel):
    id: int
    script_version_id: int
    position: int
    narration: str
    visual_prompt: str
    duration_seconds: float
    media_asset_id: int | None


class SceneUpdate(BaseModel):
    narration: str | None = Field(default=None, min_length=1, max_length=2000)
    duration_seconds: float | None = Field(default=None, ge=1, le=60)
    media_asset_id: int | None = None
    clear_media: bool = False


class AssetOut(ORMModel):
    id: int
    project_id: int
    kind: str
    filename: str | None
    content_type: str | None
    size_bytes: int | None
    status: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ShotOut(ORMModel):
    id: int
    scene_id: int
    position: int
    asset_id: int | None
    start: float
    duration: float
    effect: str
    clip_start: float
    role: str


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=300)
    content_type: str
    size_bytes: int = Field(gt=0)


class UploadTicket(BaseModel):
    asset: AssetOut
    upload_url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]


class ApprovalCreate(BaseModel):
    gate: Literal["script", "render", "publish"]
    target_id: int
    approved: bool = True
    note: str = Field(default="", max_length=2000)


class ApprovalOut(ORMModel):
    id: int
    gate: str
    target_id: int
    approved: bool
    actor: str
    note: str
    created_at: datetime


class RenderCreate(BaseModel):
    script_version_id: int
    idempotency_key: str = Field(min_length=4, max_length=200)
    estimated_cost_cents: int = Field(default=100, ge=0)


class RenderOut(ORMModel):
    id: int
    project_id: int
    script_version_id: int
    status: str
    artifact_kind: str | None
    progress: int
    attempts: int
    cost_cents: int
    error: str | None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @field_validator("timeline", mode="before")
    @classmethod
    def default_timeline(cls, value: Any) -> Any:
        return value or []


class PreviewOut(BaseModel):
    url: str
    kind: str


class ConnectionCreate(BaseModel):
    platform: Literal["youtube", "tiktok", "local"]
    external_account_id: str = Field(default="", max_length=500)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    account_id: int | None = None


class ConnectionOut(BaseModel):
    id: int
    project_id: int
    platform: str
    external_account_id: str
    enabled: bool
    authorized: bool
    created_at: datetime
    account_id: int | None = None
    display_name: str = ""


class PlatformCredentialOut(BaseModel):
    platform: str
    label: str
    client_id: str
    has_secret: bool
    source: Literal["organization", "env", "none"]
    live_enabled: bool
    live_forced_by_env: bool
    redirect_uri: str
    console_url: str
    updated_by: str = ""
    updated_at: datetime | None = None


class PlatformCredentialUpdate(BaseModel):
    client_id: str = Field(min_length=1, max_length=500)
    client_secret: str | None = Field(default=None, max_length=2000)
    live_enabled: bool = False

    @field_validator("client_id", "client_secret")
    @classmethod
    def strip(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ChannelAccountOut(BaseModel):
    id: int
    platform: str
    external_account_id: str
    display_name: str
    enabled: bool
    authorized: bool
    can_refresh: bool
    expires_at: datetime | None
    projects: int
    updated_at: datetime


class OAuthCallback(BaseModel):
    platform: str
    code: str
    state: str


class PublicationCreate(BaseModel):
    render_id: int
    connection_id: int
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    idempotency_key: str = Field(min_length=4, max_length=200)
    live: bool = False
    scheduled_at: datetime | None = None


class PublicationOut(ORMModel):
    id: int
    project_id: int
    render_id: int
    connection_id: int
    title: str
    description: str
    live: bool
    status: str
    error: str | None
    external_id: str | None
    url: str | None
    simulated: bool
    scheduled_at: datetime | None
    published_at: datetime | None
    created_at: datetime


class CalendarItem(PublicationOut):
    project_name: str
    platform: str


class MetricCreate(BaseModel):
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    average_view_duration: float | None = Field(default=None, ge=0)
    average_view_percentage: float | None = Field(default=None, ge=0, le=100)
    window_hours: int = Field(default=24, ge=1)


class MetricOut(ORMModel):
    id: int
    publication_id: int
    views: int
    likes: int
    comments: int
    shares: int
    average_view_duration: float | None
    average_view_percentage: float | None
    window_hours: int
    captured_at: datetime


class ProjectMetrics(BaseModel):
    views: int
    likes: int
    comments: int
    shares: int
    engagement_rate: float
    publications_measured: int


class InsightOut(ORMModel):
    id: int
    project_id: int
    kind: str
    text: str
    evidence: dict[str, Any]
    created_at: datetime


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    hypothesis: str = Field(min_length=1, max_length=5000)
    variants: dict[str, Any] = Field(default_factory=dict)


class ExperimentOut(ORMModel):
    id: int
    project_id: int
    name: str
    hypothesis: str
    variants: dict[str, Any]
    status: str
    created_at: datetime


class AuditOut(ORMModel):
    id: int
    action: str
    actor: str
    entity_type: str
    entity_id: int | None
    payload: dict[str, Any]
    created_at: datetime


class ProjectOverview(BaseModel):
    project: ProjectOut
    brief: BriefOut | None
    sources: list[SourceOut]
    scripts: list[ScriptOut]
    latest_script: ScriptOut | None
    scenes: list[SceneOut]
    approvals: list[ApprovalOut]
    latest_render: RenderOut | None
    connections: list[ConnectionOut]
    publications: list[PublicationOut]
    assets: list[AssetOut]


class DashboardRender(BaseModel):
    render: RenderOut
    project: ProjectOut
    scenes: int


class DashboardOut(BaseModel):
    projects: list[ProjectOut]
    project_count: int
    status_counts: dict[str, int]
    spent_cents: int
    monthly_budget_cents: int
    connected_channels: int
    active_render: DashboardRender | None
    latest_insight: InsightOut | None
    published_count: int


class AutopilotSettingsOut(ORMModel):
    enabled: bool
    script_threshold: int
    cadence_hours: int
    auto_publish: bool
    live_publish: bool
    platform: str
    language: str
    niche: str
    audience: str
    duration_seconds: int
    video_budget_cents: int
    banned_topics: list[str]
    press_kit_urls: list[str]


class AutopilotSettingsUpdate(BaseModel):
    enabled: bool | None = None
    script_threshold: int | None = Field(default=None, ge=0, le=100)
    cadence_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    auto_publish: bool | None = None
    live_publish: bool | None = None
    platform: Literal["local", "youtube", "tiktok"] | None = None
    language: Language | None = None
    niche: str | None = Field(default=None, max_length=500)
    audience: str | None = Field(default=None, max_length=500)
    duration_seconds: int | None = Field(default=None, ge=15, le=600)
    video_budget_cents: int | None = Field(default=None, ge=0)
    banned_topics: list[str] | None = None
    press_kit_urls: list[str] | None = None


class AutopilotProjectCreate(BaseModel):
    topic: str | None = Field(default=None, min_length=2, max_length=500)
    angle: str = Field(default="", max_length=2000)
    language: Language | None = None
    audience: str | None = Field(default=None, max_length=500)
    duration_seconds: int | None = Field(default=None, ge=15, le=600)


class AutopilotResume(BaseModel):
    approve: bool = False


class StageRunOut(ORMModel):
    id: int
    project_id: int
    stage: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int
    cost_cents: int
    score: float | None
    detail: dict[str, Any]


class InboxItem(BaseModel):
    project: ProjectOut
    stage: str
    reason: str
    blocked_at: datetime | None


class TopicOut(ORMModel):
    id: int
    topic: str
    angle: str
    predicted_score: float
    reason: str
    source: dict[str, Any]
    status: str
    project_id: int | None
    created_at: datetime


class PlaybookRuleOut(ORMModel):
    id: int
    key: str
    text: str
    value: dict[str, Any]
    confidence: float
    evidence: dict[str, Any]
    active: bool
    created_at: datetime


class StageStat(BaseModel):
    stage: str
    runs: int
    avg_seconds: float
    avg_cost_cents: float
    blocked: int
    failed: int
    avg_score: float | None


class AutopilotOverview(BaseModel):
    enabled: bool
    produced: int
    published: int
    in_flight: list[ProjectOut]
    inbox_count: int
    auto_approval_rate: float
    approvals_total: int
    stage_stats: list[StageStat]
    retention_curve: list[list[float]]
    retention_samples: int
    rules: list[PlaybookRuleOut]
    topics_proposed: int
    recent_runs: list[StageRunOut]
    integrations: dict[str, bool]


class RetentionIn(BaseModel):
    points: list[list[float]] = Field(min_length=2)


class RetentionOut(ORMModel):
    publication_id: int
    points: list[list[float]]
    drops: list[dict[str, Any]]
    captured_at: datetime


class VoiceOut(BaseModel):
    id: str
    label: str
    language: str
    gender: str
    sample_available: bool = False
