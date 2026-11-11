from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Timestamped:
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Organization(Timestamped, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200))
    monthly_budget_cents: Mapped[int] = mapped_column(Integer, default=25_000)
    voice: Mapped[str] = mapped_column(String(50), default="pf_dora")
    voices: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)


class User(Timestamped, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Timestamped, Base):
    __tablename__ = "memberships"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="editor")
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)


class Project(Timestamped, Base):
    __tablename__ = "projects"
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    budget_cents: Mapped[int] = mapped_column(Integer, default=1000)
    spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str] = mapped_column(String(10), default="pt-BR")
    autopilot: Mapped[bool] = mapped_column(Boolean, default=False)
    autopilot_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    autopilot_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Brief(Timestamped, Base):
    __tablename__ = "briefs"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    topic: Mapped[str] = mapped_column(String(500))
    audience: Mapped[str] = mapped_column(String(500), default="general")
    objective: Mapped[str] = mapped_column(String(500), default="engagement")
    language: Mapped[str] = mapped_column(String(10), default="pt-BR")
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ResearchDossier(Timestamped, Base):
    __tablename__ = "research_dossiers"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    language: Mapped[str] = mapped_column(String(10), default="pt-BR")
    summary: Mapped[str] = mapped_column(Text, default="")
    facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    angles: Mapped[list[str]] = mapped_column(JSON, default=list)
    hooks: Mapped[list[str]] = mapped_column(JSON, default=list)
    controversies: Mapped[list[str]] = mapped_column(JSON, default=list)
    video_moments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(100), default="local")
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)


class Source(Timestamped, Base):
    __tablename__ = "sources"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(100), default="local")


class ScriptVersion(Timestamped, Base):
    __tablename__ = "script_versions"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    author: Mapped[str] = mapped_column(String(200), default="system")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    __table_args__ = (UniqueConstraint("project_id", "version"),)


class Asset(Timestamped, Base):
    __tablename__ = "assets"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    uri: Mapped[str] = mapped_column(String(2000))
    filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ready")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class Scene(Timestamped, Base):
    __tablename__ = "scenes"
    script_version_id: Mapped[int] = mapped_column(ForeignKey("script_versions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    narration: Mapped[str] = mapped_column(Text)
    visual_prompt: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(Float, default=5)
    media_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)


class SceneShot(Timestamped, Base):
    __tablename__ = "scene_shots"
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    start: Mapped[float] = mapped_column(Float, default=0)
    duration: Mapped[float] = mapped_column(Float, default=3)
    effect: Mapped[str] = mapped_column(String(30), default="zoom_in")
    clip_start: Mapped[float] = mapped_column(Float, default=0)
    role: Mapped[str] = mapped_column(String(30), default="broll")


class Render(Timestamped, Base):
    __tablename__ = "renders"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    script_version_id: Mapped[int] = mapped_column(ForeignKey("script_versions.id"))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    artifact_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    artifact_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Approval(Timestamped, Base):
    __tablename__ = "approvals"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    gate: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[int] = mapped_column(Integer)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    actor: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("project_id", "gate", "target_id"),)


class ChannelConnection(Timestamped, Base):
    __tablename__ = "channel_connections"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    platform: Mapped[str] = mapped_column(String(30))
    external_account_id: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("project_id", "platform", "external_account_id"),)


class Publication(Timestamped, Base):
    __tablename__ = "publications"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    render_id: Mapped[int] = mapped_column(ForeignKey("renders.id"))
    connection_id: Mapped[int] = mapped_column(ForeignKey("channel_connections.id"))
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    live: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    external_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MetricSnapshot(Timestamped, Base):
    __tablename__ = "metric_snapshots"
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    average_view_duration: Mapped[float | None] = mapped_column(nullable=True)
    average_view_percentage: Mapped[float | None] = mapped_column(nullable=True)
    window_hours: Mapped[int] = mapped_column(Integer, default=24)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("publication_id", "window_hours"),)


class Experiment(Timestamped, Base):
    __tablename__ = "experiments"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    hypothesis: Mapped[str] = mapped_column(Text)
    variants: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="draft")


class Insight(Timestamped, Base):
    __tablename__ = "insights"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50), default="performance")
    text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RetentionCurve(Timestamped, Base):
    __tablename__ = "retention_curves"
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), unique=True)
    points: Mapped[list[list[float]]] = mapped_column(JSON, default=list)
    drops: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AutopilotSettings(Timestamped, Base):
    __tablename__ = "autopilot_settings"
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    script_threshold: Mapped[int] = mapped_column(Integer, default=75)
    cadence_hours: Mapped[int] = mapped_column(Integer, default=24)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=True)
    live_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    platform: Mapped[str] = mapped_column(String(30), default="local")
    language: Mapped[str] = mapped_column(String(10), default="pt-BR")
    niche: Mapped[str] = mapped_column(String(500), default="")
    audience: Mapped[str] = mapped_column(String(500), default="público geral")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=60)
    video_budget_cents: Mapped[int] = mapped_column(Integer, default=500)
    banned_topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    press_kit_urls: Mapped[list[str]] = mapped_column(JSON, default=list)


class StageRun(Timestamped, Base):
    __tablename__ = "stage_runs"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PlaybookRule(Timestamped, Base):
    __tablename__ = "playbook_rules"
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TopicSuggestion(Timestamped, Base):
    __tablename__ = "topic_suggestions"
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    topic: Mapped[str] = mapped_column(String(500))
    angle: Mapped[str] = mapped_column(Text, default="")
    predicted_score: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)


class AuditEvent(Timestamped, Base):
    __tablename__ = "audit_events"
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(200), default="system")
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
