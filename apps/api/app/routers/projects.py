from collections import Counter
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from video_ai_contracts import ProjectStatus

from ..auth import CurrentContext, EditorContext
from ..channels import is_authorized
from ..deps import DbSession, audit, require_project, set_status
from ..models import (
    Approval,
    Asset,
    AuditEvent,
    Brief,
    ChannelConnection,
    Insight,
    Project,
    Publication,
    Render,
    Scene,
    ScriptVersion,
    Source,
    utcnow,
)
from ..schemas import (
    ApprovalOut,
    AssetOut,
    AuditOut,
    BriefCreate,
    BriefOut,
    CalendarItem,
    ConnectionOut,
    DashboardOut,
    DashboardRender,
    InsightOut,
    ProjectCreate,
    ProjectOut,
    ProjectOverview,
    ProjectUpdate,
    PublicationOut,
    RenderOut,
    SceneOut,
    SceneUpdate,
    ScriptOut,
    ScriptUpdate,
    SourceOut,
)

router = APIRouter(tags=["projects"])

COST_ACTIONS = {"research.generated", "script.generated", "script.reviewed", "media.sourced", "render.completed"}


def connection_out(connection: ChannelConnection) -> ConnectionOut:
    return ConnectionOut(
        id=connection.id,
        project_id=connection.project_id,
        platform=connection.platform,
        external_account_id=connection.external_account_id,
        enabled=connection.enabled,
        authorized=is_authorized(connection),
        created_at=connection.created_at,
        account_id=connection.account_id,
        display_name=connection.account.display_name if connection.account else "",
    )


def latest_brief(db: DbSession, project_id: int) -> Brief | None:
    return db.scalar(select(Brief).where(Brief.project_id == project_id).order_by(Brief.id.desc()))


def latest_script(db: DbSession, project_id: int) -> ScriptVersion | None:
    return db.scalar(
        select(ScriptVersion).where(ScriptVersion.project_id == project_id).order_by(ScriptVersion.version.desc())
    )


def scenes_for(db: DbSession, script_id: int) -> list[Scene]:
    return list(db.scalars(select(Scene).where(Scene.script_version_id == script_id).order_by(Scene.position)))


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, ctx: EditorContext, db: DbSession):
    project = Project(
        name=body.name,
        budget_cents=body.budget_cents,
        language=body.language,
        organization_id=ctx.organization.id,
        created_by=ctx.user.id,
    )
    db.add(project)
    db.flush()
    audit(db, project.id, "project.created", project, ctx.actor)
    db.commit()
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(ctx: CurrentContext, db: DbSession, status: str | None = None, q: str | None = None):
    query = select(Project).where(Project.organization_id == ctx.organization.id)
    if status:
        query = query.where(Project.status == status)
    if q:
        query = query.where(Project.name.ilike(f"%{q}%"))
    return list(db.scalars(query.order_by(Project.updated_at.desc(), Project.id.desc())))


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, ctx: CurrentContext, db: DbSession):
    return require_project(db, ctx, project_id)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, ctx: EditorContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(project, key, value)
    audit(db, project.id, "project.updated", project, ctx.actor, **changes)
    db.commit()
    return project


@router.get("/projects/{project_id}/overview", response_model=ProjectOverview)
def project_overview(project_id: int, ctx: CurrentContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    scripts = list(
        db.scalars(
            select(ScriptVersion).where(ScriptVersion.project_id == project_id).order_by(ScriptVersion.version.desc())
        )
    )
    current = scripts[0] if scripts else None
    render = db.scalar(select(Render).where(Render.project_id == project_id).order_by(Render.id.desc()))
    return ProjectOverview(
        project=ProjectOut.model_validate(project),
        brief=latest_brief(db, project_id),
        sources=list(db.scalars(select(Source).where(Source.project_id == project_id).order_by(Source.id.desc()))),
        scripts=scripts,
        latest_script=current,
        scenes=scenes_for(db, current.id) if current else [],
        approvals=list(db.scalars(select(Approval).where(Approval.project_id == project_id).order_by(Approval.id))),
        latest_render=render,
        connections=[
            connection_out(item)
            for item in db.scalars(select(ChannelConnection).where(ChannelConnection.project_id == project_id))
        ],
        publications=list(
            db.scalars(select(Publication).where(Publication.project_id == project_id).order_by(Publication.id.desc()))
        ),
        assets=list(
            db.scalars(
                select(Asset)
                .where(Asset.project_id == project_id, Asset.kind.in_(["image", "video"]), Asset.status == "ready")
                .order_by(Asset.id.desc())
            )
        ),
    )


@router.put("/projects/{project_id}/brief", response_model=BriefOut)
def upsert_brief(project_id: int, body: BriefCreate, ctx: EditorContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    brief = latest_brief(db, project_id)
    if brief:
        for key, value in body.model_dump().items():
            setattr(brief, key, value)
    else:
        brief = Brief(project_id=project_id, **body.model_dump())
        db.add(brief)
    project.language = body.language
    project.updated_at = utcnow()
    db.flush()
    audit(db, project_id, "brief.saved", brief, ctx.actor)
    db.commit()
    return brief


@router.get("/projects/{project_id}/brief", response_model=BriefOut)
def get_brief(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    brief = latest_brief(db, project_id)
    if not brief:
        raise HTTPException(404, "Briefing não encontrado")
    return brief


@router.get("/projects/{project_id}/sources", response_model=list[SourceOut])
def list_sources(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(db.scalars(select(Source).where(Source.project_id == project_id).order_by(Source.id.desc())))


@router.get("/projects/{project_id}/scripts", response_model=list[ScriptOut])
def list_scripts(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(
        db.scalars(
            select(ScriptVersion).where(ScriptVersion.project_id == project_id).order_by(ScriptVersion.version.desc())
        )
    )


@router.put("/projects/{project_id}/scripts/{script_id}", response_model=ScriptOut, status_code=201)
def edit_script(project_id: int, script_id: int, body: ScriptUpdate, ctx: EditorContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    base = db.get(ScriptVersion, script_id)
    if not base or base.project_id != project_id:
        raise HTTPException(404, "Versão de roteiro não encontrada")
    if body.content.strip() == base.content.strip():
        return base
    version = (db.scalar(select(func.max(ScriptVersion.version)).where(ScriptVersion.project_id == project_id)) or 0) + 1
    script = ScriptVersion(project_id=project_id, version=version, content=body.content.strip(), author=ctx.actor)
    db.add(script)
    db.flush()
    audit(db, project_id, "script.edited", script, ctx.actor, base_version=base.version)
    set_status(db, project, ProjectStatus.REVIEW, ctx.actor, "nova versão de roteiro")
    db.commit()
    return script


@router.get("/projects/{project_id}/scripts/{script_id}/scenes", response_model=list[SceneOut])
def list_scenes(project_id: int, script_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    script = db.get(ScriptVersion, script_id)
    if not script or script.project_id != project_id:
        raise HTTPException(404, "Versão de roteiro não encontrada")
    return scenes_for(db, script_id)


@router.patch("/scenes/{scene_id}", response_model=SceneOut)
def update_scene(scene_id: int, body: SceneUpdate, ctx: EditorContext, db: DbSession):
    scene = db.get(Scene, scene_id)
    script = db.get(ScriptVersion, scene.script_version_id) if scene else None
    if not scene or not script:
        raise HTTPException(404, "Cena não encontrada")
    require_project(db, ctx, script.project_id)
    if body.narration is not None:
        scene.narration = body.narration.strip()
        scene.visual_prompt = f"Vertical cinematic scene illustrating: {scene.narration[:120]}"
    if body.duration_seconds is not None:
        scene.duration_seconds = body.duration_seconds
    if body.clear_media:
        scene.media_asset_id = None
    elif body.media_asset_id is not None:
        asset = db.get(Asset, body.media_asset_id)
        if (
            not asset
            or asset.project_id != script.project_id
            or asset.status != "ready"
            or asset.kind not in {"image", "video"}
        ):
            raise HTTPException(422, "Mídia inválida para esta cena")
        scene.media_asset_id = asset.id
    audit(db, script.project_id, "scene.updated", scene, ctx.actor)
    db.commit()
    return scene


@router.get("/projects/{project_id}/approvals", response_model=list[ApprovalOut])
def list_approvals(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(db.scalars(select(Approval).where(Approval.project_id == project_id).order_by(Approval.id)))


@router.get("/projects/{project_id}/audit", response_model=list[AuditOut])
def list_audit(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(
        db.scalars(select(AuditEvent).where(AuditEvent.project_id == project_id).order_by(AuditEvent.id.desc()))
    )


def _org_project_ids(db: DbSession, organization_id: int) -> list[int]:
    return list(db.scalars(select(Project.id).where(Project.organization_id == organization_id)))


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(ctx: CurrentContext, db: DbSession):
    projects = list(
        db.scalars(
            select(Project)
            .where(Project.organization_id == ctx.organization.id)
            .order_by(Project.updated_at.desc(), Project.id.desc())
        )
    )
    ids = [project.id for project in projects]
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = 0
    if ids:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.project_id.in_(ids),
                AuditEvent.action.in_(COST_ACTIONS),
                AuditEvent.created_at >= month_start,
            )
        )
        spent = sum(int((event.payload or {}).get("cost_cents", 0)) for event in events)
    active = None
    if ids:
        render = db.scalar(
            select(Render)
            .where(Render.project_id.in_(ids), Render.status.in_(["queued", "processing"]))
            .order_by(Render.id.desc())
        ) or db.scalar(select(Render).where(Render.project_id.in_(ids)).order_by(Render.id.desc()))
        if render:
            scene_count = db.scalar(select(func.count()).where(Scene.script_version_id == render.script_version_id))
            active = DashboardRender(
                render=RenderOut.model_validate(render),
                project=ProjectOut.model_validate(db.get(Project, render.project_id)),
                scenes=scene_count or 0,
            )
    connected = (
        db.scalar(
            select(func.count()).where(ChannelConnection.project_id.in_(ids), ChannelConnection.enabled.is_(True))
        )
        if ids
        else 0
    )
    insight = (
        db.scalar(select(Insight).where(Insight.project_id.in_(ids)).order_by(Insight.id.desc())) if ids else None
    )
    published = (
        db.scalar(select(func.count()).where(Publication.project_id.in_(ids), Publication.status == "published"))
        if ids
        else 0
    )
    return DashboardOut(
        projects=projects[:6],
        project_count=len(projects),
        status_counts=dict(Counter(project.status for project in projects)),
        spent_cents=spent,
        monthly_budget_cents=ctx.organization.monthly_budget_cents,
        connected_channels=connected or 0,
        active_render=active,
        latest_insight=InsightOut.model_validate(insight) if insight else None,
        published_count=published or 0,
    )


@router.get("/sources", response_model=list[SourceOut])
def organization_sources(ctx: CurrentContext, db: DbSession):
    ids = _org_project_ids(db, ctx.organization.id)
    if not ids:
        return []
    return list(db.scalars(select(Source).where(Source.project_id.in_(ids)).order_by(Source.id.desc())))


@router.get("/calendar", response_model=list[CalendarItem])
def calendar(ctx: CurrentContext, db: DbSession, start: datetime | None = None, end: datetime | None = None):
    rows = db.execute(
        select(Publication, Project.name, ChannelConnection.platform)
        .join(Project, Project.id == Publication.project_id)
        .join(ChannelConnection, ChannelConnection.id == Publication.connection_id)
        .where(Project.organization_id == ctx.organization.id)
        .order_by(func.coalesce(Publication.scheduled_at, Publication.created_at))
    )
    items = []
    for publication, project_name, platform in rows:
        when = publication.scheduled_at or publication.created_at
        if (start and when < start) or (end and when > end):
            continue
        items.append(
            CalendarItem(
                **PublicationOut.model_validate(publication).model_dump(),
                project_name=project_name,
                platform=platform,
            )
        )
    return items
