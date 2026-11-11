import json

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from redis import Redis
from sqlalchemy import select

from video_ai_contracts import ProjectStatus

from ..adapters import voice_for
from ..auth import Context, CurrentContext, EditorContext
from ..config import get_settings
from ..deps import DbSession, approved, audit, require_budget, require_project, set_status
from ..models import Render, ScriptVersion
from ..schemas import PreviewOut, RenderCreate, RenderOut
from ..storage import LocalStorage, Storage, get_storage
from .generation import ensure_storyboard

router = APIRouter(tags=["renders"])
RENDER_QUEUE = "video-ai:render-jobs"
CONTENT_TYPES = {"video": "video/mp4", "manifest": "application/json"}


def require_render(db: DbSession, ctx: Context, render_id: int) -> Render:
    render = db.get(Render, render_id)
    if not render:
        raise HTTPException(404, "Render não encontrado")
    require_project(db, ctx, render.project_id)
    return render


@router.post("/projects/{project_id}/renders", response_model=RenderOut, status_code=201)
def create_render(
    project_id: int,
    body: RenderCreate,
    ctx: EditorContext,
    db: DbSession,
    storage: Storage = Depends(get_storage),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = idempotency_header or body.idempotency_key
    existing = db.scalar(select(Render).where(Render.idempotency_key == key))
    if existing:
        if existing.project_id != project_id:
            raise HTTPException(409, "Chave de idempotência pertence a outro projeto")
        require_project(db, ctx, project_id)
        return existing
    project = require_project(db, ctx, project_id)
    script = db.get(ScriptVersion, body.script_version_id)
    if not script or script.project_id != project_id:
        raise HTTPException(404, "Versão de roteiro não encontrada")
    if not approved(db, project_id, "script", script.id):
        raise HTTPException(409, "O roteiro precisa ser aprovado antes da renderização")
    require_budget(project, body.estimated_cost_cents)
    scenes = ensure_storyboard(db, script)
    render = Render(
        project_id=project_id,
        script_version_id=script.id,
        status="queued",
        idempotency_key=key,
        cost_cents=body.estimated_cost_cents,
    )
    db.add(render)
    db.flush()
    audit(
        db,
        project_id,
        "render.queued",
        render,
        ctx.actor,
        scenes=len(scenes),
        voice=voice_for(ctx.organization, project.language or "pt-BR"),
        engine="kokoro+ffmpeg",
    )
    set_status(db, project, ProjectStatus.PROCESSING, ctx.actor, "renderização solicitada")
    db.commit()

    settings = get_settings()
    if settings.redis_url:
        Redis.from_url(settings.redis_url).rpush(RENDER_QUEUE, json.dumps({"render_id": render.id, "attempt": 1}))
        return render

    from pipeline.service import execute_render, mark_failed

    try:
        execute_render(db, render.id, storage)
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as render.error
        mark_failed(db, render.id, str(exc))
    db.refresh(render)
    return render


@router.get("/projects/{project_id}/renders", response_model=list[RenderOut])
def list_renders(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(db.scalars(select(Render).where(Render.project_id == project_id).order_by(Render.id.desc())))


@router.get("/renders/{render_id}", response_model=RenderOut)
def get_render(render_id: int, ctx: CurrentContext, db: DbSession):
    return require_render(db, ctx, render_id)


@router.post("/renders/{render_id}/retry", response_model=RenderOut)
def retry_render(render_id: int, ctx: EditorContext, db: DbSession):
    render = require_render(db, ctx, render_id)
    if render.status != "failed":
        raise HTTPException(409, "Apenas renders com falha podem ser reenviados")
    settings = get_settings()
    render.status, render.error, render.progress, render.attempts = "queued", None, 0, 0
    audit(db, render.project_id, "render.retried", render, ctx.actor)
    db.commit()
    if settings.redis_url:
        Redis.from_url(settings.redis_url).rpush(RENDER_QUEUE, json.dumps({"render_id": render.id, "attempt": 1}))
    return render


@router.get("/renders/{render_id}/preview", response_model=PreviewOut)
def render_preview(render_id: int, ctx: CurrentContext, db: DbSession, storage: Storage = Depends(get_storage)):
    render = require_render(db, ctx, render_id)
    if render.status != "completed" or not render.artifact_uri:
        raise HTTPException(409, "O render ainda não foi concluído")
    kind = render.artifact_kind or "video"
    url = storage.presign_get(render.artifact_uri, CONTENT_TYPES.get(kind))
    return PreviewOut(url=url or f"/api/v1/renders/{render.id}/content", kind=kind)


@router.get("/renders/{render_id}/content")
def render_content(render_id: int, ctx: CurrentContext, db: DbSession, storage: Storage = Depends(get_storage)):
    render = require_render(db, ctx, render_id)
    if render.status != "completed" or not render.artifact_uri:
        raise HTTPException(409, "O render ainda não foi concluído")
    media_type = CONTENT_TYPES.get(render.artifact_kind or "video", "application/octet-stream")
    if isinstance(storage, LocalStorage):
        return FileResponse(storage.path(render.artifact_uri), media_type=media_type)
    return RedirectResponse(storage.presign_get(render.artifact_uri, media_type))
