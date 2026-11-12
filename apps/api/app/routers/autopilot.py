import logging
import shutil
from collections import defaultdict
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from .. import autopilot as engine
from ..ai import AzureOpenAIProvider, ai_configured
from ..auth import CurrentContext, EditorContext, OwnerContext
from ..channels import OAUTH_PLATFORMS, live_allowed, oauth_client
from ..config import get_settings
from ..deps import DbSession, audit, require_project
from ..learning import active_rules, plan_topics, store_retention, update_playbook
from ..models import Approval, Project, Publication, RetentionCurve, StageRun, TopicSuggestion
from ..oauth import OAuthService
from ..schemas import (
    AutopilotOverview,
    AutopilotProjectCreate,
    AutopilotResume,
    AutopilotSettingsOut,
    AutopilotSettingsUpdate,
    InboxItem,
    PlaybookRuleOut,
    ProjectOut,
    RetentionIn,
    RetentionOut,
    StageRunOut,
    StageStat,
    TopicOut,
)
from ..storage import Storage, get_storage
from .publications import require_publication

router = APIRouter(tags=["autopilot"])
logger = logging.getLogger("narra.autopilot")


def integrations(db: DbSession, organization_id: int) -> dict[str, bool]:
    settings = get_settings()
    oauth = OAuthService(settings)
    return {
        "ai": ai_configured(settings),
        "transcription": bool(ai_configured(settings) and settings.azure_openai_transcribe_deployment),
        "articles": bool(settings.tavily_api_key),
        "youtube": bool(settings.youtube_api_key),
        "pexels": bool(settings.pexels_api_key),
        "pixabay": bool(settings.pixabay_api_key),
        "open_media": True,
        "fair_use_clips": settings.fair_use_clips_enabled and bool(shutil.which("yt-dlp")),
        "queue": bool(settings.redis_url),
        **{f"{platform}_login": oauth_client(db, organization_id, platform, oauth) is not None for platform in OAUTH_PLATFORMS},
        "live_publish": any(live_allowed(db, organization_id, platform, settings) for platform in OAUTH_PLATFORMS),
    }


def _org_projects(db: DbSession, organization_id: int) -> list[int]:
    return list(db.scalars(select(Project.id).where(Project.organization_id == organization_id)))


@router.get("/autopilot/settings", response_model=AutopilotSettingsOut)
def get_autopilot_settings(ctx: CurrentContext, db: DbSession):
    config = engine.settings_for(db, ctx.organization.id)
    db.commit()
    return config


@router.put("/autopilot/settings", response_model=AutopilotSettingsOut)
def update_autopilot_settings(body: AutopilotSettingsUpdate, ctx: OwnerContext, db: DbSession):
    config = engine.settings_for(db, ctx.organization.id)
    changes = body.model_dump(exclude_none=True)
    if "banned_topics" in changes:
        changes["banned_topics"] = [item.strip() for item in changes["banned_topics"] if item.strip()][:100]
    if "press_kit_urls" in changes:
        urls = [item.strip() for item in changes["press_kit_urls"] if item.strip()]
        if any(not url.startswith(("https://", "http://")) for url in urls):
            raise HTTPException(422, "URLs de press kit devem começar com http(s)://")
        changes["press_kit_urls"] = urls[:50]
    for key, value in changes.items():
        setattr(config, key, value)
    audit(db, None, "autopilot.settings_updated", config, ctx.actor, **{k: v for k, v in changes.items() if k != "press_kit_urls"})
    db.commit()
    return config


@router.get("/autopilot/integrations")
def get_integrations(ctx: CurrentContext, db: DbSession) -> dict[str, bool]:
    return integrations(db, ctx.organization.id)


@router.post("/autopilot/integrations/test")
def test_ai(ctx: OwnerContext) -> dict:
    settings = get_settings()
    if not ai_configured(settings):
        raise HTTPException(409, "Defina AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY e AZURE_OPENAI_CHAT_DEPLOYMENT no .env")
    provider = AzureOpenAIProvider(settings)
    try:
        report = provider.check_connection()
    finally:
        provider.client.close()
    logger.info("AI connection test by %s: ok=%s", ctx.actor, report.get("ok"))
    return report


@router.post("/autopilot/projects", response_model=ProjectOut, status_code=201)
def start_autopilot_project(body: AutopilotProjectCreate, ctx: EditorContext, db: DbSession, storage: Storage = Depends(get_storage)):
    suggestion = None
    topic = body.topic
    if not topic:
        suggestion = engine._next_topic(db, ctx.organization.id)
        if suggestion is None:
            plan_topics(db, ctx.organization, ctx.actor)
            suggestion = engine._next_topic(db, ctx.organization.id)
        if suggestion is None:
            raise HTTPException(409, "Nenhum tema disponível: defina o nicho do piloto automático ou informe um tema")
        topic = suggestion.topic
    project = engine.create_project(
        db,
        ctx.organization,
        ctx.actor,
        topic,
        angle=body.angle or (suggestion.angle if suggestion else ""),
        language=body.language,
        audience=body.audience,
        duration_seconds=body.duration_seconds,
        created_by=ctx.user.id,
        suggestion=suggestion,
    )
    engine.continue_project(db, project.id, storage)
    db.refresh(project)
    return project


@router.post("/projects/{project_id}/autopilot/start", response_model=ProjectOut)
def enable_autopilot(project_id: int, ctx: EditorContext, db: DbSession, storage: Storage = Depends(get_storage)):
    project = require_project(db, ctx, project_id)
    project.autopilot, project.autopilot_reason = True, None
    project.autopilot_stage = engine.stage_for_existing(db, project)
    audit(db, project.id, "autopilot.enabled", project, ctx.actor, stage=project.autopilot_stage)
    engine.continue_project(db, project.id, storage)
    db.refresh(project)
    return project


@router.post("/projects/{project_id}/autopilot/stop", response_model=ProjectOut)
def stop_autopilot(project_id: int, ctx: EditorContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    project.autopilot = False
    audit(db, project.id, "autopilot.stopped", project, ctx.actor, stage=project.autopilot_stage)
    db.commit()
    return project


@router.post("/projects/{project_id}/autopilot/resume", response_model=ProjectOut)
def resume_autopilot(project_id: int, body: AutopilotResume, ctx: EditorContext, db: DbSession, storage: Storage = Depends(get_storage)):
    project = require_project(db, ctx, project_id)
    if project.autopilot_stage != "needs_review":
        raise HTTPException(409, "O projeto não está aguardando revisão")
    engine.resume(db, project, ctx.actor, body.approve, storage)
    db.refresh(project)
    return project


@router.get("/projects/{project_id}/autopilot/runs", response_model=list[StageRunOut])
def project_runs(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(db.scalars(select(StageRun).where(StageRun.project_id == project_id).order_by(StageRun.id)))


@router.get("/autopilot/inbox", response_model=list[InboxItem])
def inbox(ctx: CurrentContext, db: DbSession):
    projects = db.scalars(
        select(Project)
        .where(Project.organization_id == ctx.organization.id, Project.autopilot_stage == "needs_review")
        .order_by(Project.updated_at.desc())
    )
    items = []
    for project in projects:
        run = db.scalar(
            select(StageRun)
            .where(StageRun.project_id == project.id, StageRun.status.in_(["blocked", "failed"]))
            .order_by(StageRun.id.desc())
        )
        items.append(
            InboxItem(
                project=ProjectOut.model_validate(project),
                stage=run.stage if run else "",
                reason=project.autopilot_reason or "",
                blocked_at=run.finished_at or run.started_at if run else None,
            )
        )
    return items


@router.get("/autopilot/topics", response_model=list[TopicOut])
def list_topics(ctx: CurrentContext, db: DbSession, status: str | None = "proposed"):
    query = select(TopicSuggestion).where(TopicSuggestion.organization_id == ctx.organization.id)
    if status:
        query = query.where(TopicSuggestion.status == status)
    return list(db.scalars(query.order_by(TopicSuggestion.predicted_score.desc(), TopicSuggestion.id.desc()).limit(50)))


@router.post("/autopilot/topics/plan", response_model=list[TopicOut])
def plan(ctx: EditorContext, db: DbSession):
    return plan_topics(db, ctx.organization, ctx.actor)


@router.post("/autopilot/topics/{topic_id}/use", response_model=ProjectOut, status_code=201)
def use_topic(topic_id: int, ctx: EditorContext, db: DbSession, storage: Storage = Depends(get_storage)):
    suggestion = db.get(TopicSuggestion, topic_id)
    if not suggestion or suggestion.organization_id != ctx.organization.id or suggestion.status != "proposed":
        raise HTTPException(404, "Tema não encontrado")
    project = engine.create_project(
        db, ctx.organization, ctx.actor, suggestion.topic, angle=suggestion.angle, created_by=ctx.user.id, suggestion=suggestion
    )
    engine.continue_project(db, project.id, storage)
    db.refresh(project)
    return project


@router.delete("/autopilot/topics/{topic_id}", status_code=204)
def reject_topic(topic_id: int, ctx: EditorContext, db: DbSession):
    suggestion = db.get(TopicSuggestion, topic_id)
    if not suggestion or suggestion.organization_id != ctx.organization.id:
        raise HTTPException(404, "Tema não encontrado")
    suggestion.status = "rejected"
    audit(db, None, "topic.rejected", suggestion, ctx.actor, topic=suggestion.topic)
    db.commit()


@router.get("/autopilot/playbook", response_model=list[PlaybookRuleOut])
def playbook(ctx: CurrentContext, db: DbSession):
    return active_rules(db, ctx.organization.id)


@router.post("/autopilot/playbook/refresh", response_model=list[PlaybookRuleOut])
def refresh_playbook(ctx: EditorContext, db: DbSession):
    update_playbook(db, ctx.organization.id, ctx.actor)
    return active_rules(db, ctx.organization.id)


@router.post("/publications/{publication_id}/retention", response_model=RetentionOut, status_code=201)
def add_retention(publication_id: int, body: RetentionIn, ctx: EditorContext, db: DbSession):
    publication = require_publication(db, ctx, publication_id)
    if any(len(point) != 2 or not 0 <= point[0] <= 1 or point[1] < 0 for point in body.points):
        raise HTTPException(422, "Cada ponto deve ser [fração do vídeo 0-1, fração da audiência]")
    curve = store_retention(db, publication, body.points)
    audit(db, publication.project_id, "retention.captured", curve, ctx.actor, drops=len(curve.drops))
    db.commit()
    return curve


@router.get("/publications/{publication_id}/retention", response_model=RetentionOut | None)
def get_retention(publication_id: int, ctx: CurrentContext, db: DbSession):
    require_publication(db, ctx, publication_id)
    return db.scalar(select(RetentionCurve).where(RetentionCurve.publication_id == publication_id))


def _average_curve(curves: list[RetentionCurve], steps: int = 10) -> list[list[float]]:
    sampled = []
    for curve in curves:
        points = sorted((float(r), float(w)) for r, w in curve.points)
        if len(points) < 2:
            continue
        row = []
        for index in range(steps + 1):
            at = index / steps
            before = max((p for p in points if p[0] <= at), default=points[0])
            after = min((p for p in points if p[0] >= at), default=points[-1])
            span = after[0] - before[0]
            row.append(before[1] if span == 0 else before[1] + (after[1] - before[1]) * (at - before[0]) / span)
        sampled.append(row)
    if not sampled:
        return []
    return [[index / steps, round(mean(row[index] for row in sampled), 3)] for index in range(steps + 1)]


@router.get("/autopilot/overview", response_model=AutopilotOverview)
def overview(ctx: CurrentContext, db: DbSession):
    config = engine.settings_for(db, ctx.organization.id)
    db.commit()
    ids = _org_projects(db, ctx.organization.id)
    autopilot_projects = list(
        db.scalars(select(Project).where(Project.organization_id == ctx.organization.id, Project.autopilot.is_(True)).order_by(Project.id.desc()))
    )
    runs = list(db.scalars(select(StageRun).where(StageRun.project_id.in_(ids)).order_by(StageRun.id.desc()))) if ids else []
    grouped: dict[str, list[StageRun]] = defaultdict(list)
    for run in runs:
        grouped[run.stage].append(run)
    stats = []
    for stage in engine.STAGES:
        items = grouped.get(stage, [])
        done = [run for run in items if run.status in {"completed", "blocked"}]
        scores = [run.score for run in items if run.score is not None]
        stats.append(
            StageStat(
                stage=stage,
                runs=len(items),
                avg_seconds=round(mean(run.duration_ms for run in done) / 1000, 1) if done else 0,
                avg_cost_cents=round(mean(run.cost_cents for run in done), 1) if done else 0,
                blocked=sum(run.status == "blocked" for run in items),
                failed=sum(run.status == "failed" for run in items),
                avg_score=round(mean(scores), 1) if scores else None,
            )
        )
    approvals = list(db.scalars(select(Approval).where(Approval.project_id.in_(ids)))) if ids else []
    automatic = sum(approval.actor == engine.ACTOR for approval in approvals)
    curves = list(
        db.scalars(select(RetentionCurve).join(Publication, Publication.id == RetentionCurve.publication_id).where(Publication.project_id.in_(ids)))
    ) if ids else []
    published = db.scalar(
        select(func.count()).where(Publication.project_id.in_([p.id for p in autopilot_projects]), Publication.status == "published")
    ) if autopilot_projects else 0
    return AutopilotOverview(
        enabled=config.enabled,
        produced=len(autopilot_projects),
        published=published or 0,
        in_flight=[ProjectOut.model_validate(p) for p in autopilot_projects if p.autopilot_stage not in engine.TERMINAL][:10],
        inbox_count=sum(p.autopilot_stage == "needs_review" for p in autopilot_projects),
        auto_approval_rate=round(automatic / len(approvals), 3) if approvals else 0,
        approvals_total=len(approvals),
        stage_stats=stats,
        retention_curve=_average_curve(curves),
        retention_samples=len(curves),
        rules=[PlaybookRuleOut.model_validate(rule) for rule in active_rules(db, ctx.organization.id)],
        topics_proposed=db.scalar(
            select(func.count()).where(TopicSuggestion.organization_id == ctx.organization.id, TopicSuggestion.status == "proposed")
        ) or 0,
        recent_runs=[StageRunOut.model_validate(run) for run in runs[:20]],
        integrations=integrations(db, ctx.organization.id),
    )
