from datetime import timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select

from ..auth import Context, CurrentContext, EditorContext
from ..config import get_settings
from ..deps import DbSession, approved, audit, require_project
from ..models import ChannelConnection, Publication, Render, utcnow
from ..oauth import OAuthService
from ..publishing import access_token_for, execute_publication
from ..adapters import publication_status
from ..retention import credits_for, with_credits
from ..schemas import PublicationCreate, PublicationOut
from ..storage import Storage, get_storage

router = APIRouter(tags=["publications"])


def require_publication(db: DbSession, ctx: Context, publication_id: int) -> Publication:
    publication = db.get(Publication, publication_id)
    if not publication:
        raise HTTPException(404, "Publicação não encontrada")
    require_project(db, ctx, publication.project_id)
    return publication


def run_publication(db: DbSession, publication: Publication, storage: Storage, actor: str) -> Publication:
    try:
        return execute_publication(db, publication, storage, get_settings(), actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except (httpx.HTTPError, OSError, KeyError) as exc:
        raise HTTPException(502, f"Falha no publicador: {exc}")


@router.post("/projects/{project_id}/publications", response_model=PublicationOut, status_code=201)
def publish(
    project_id: int,
    body: PublicationCreate,
    ctx: EditorContext,
    db: DbSession,
    storage: Storage = Depends(get_storage),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = idempotency_header or body.idempotency_key
    existing = db.scalar(select(Publication).where(Publication.idempotency_key == key))
    if existing:
        if existing.project_id != project_id:
            raise HTTPException(409, "Chave de idempotência pertence a outro projeto")
        require_project(db, ctx, project_id)
        return existing
    require_project(db, ctx, project_id)
    render = db.get(Render, body.render_id)
    connection = db.get(ChannelConnection, body.connection_id)
    if not render or render.project_id != project_id or render.status != "completed":
        raise HTTPException(409, "É necessário um render concluído")
    if not connection or connection.project_id != project_id or not connection.enabled:
        raise HTTPException(409, "É necessária uma conexão de canal ativa")
    if not approved(db, project_id, "publish", render.id):
        raise HTTPException(409, "A publicação precisa ser aprovada")
    settings = get_settings()
    if body.live:
        if not settings.allow_live_publish:
            raise HTTPException(400, "Publicação real desativada (ALLOW_LIVE_PUBLISH=false)")
        if connection.platform == "local" or not access_token_for(connection, OAuthService(settings)):
            raise HTTPException(400, "Conecte o canal via OAuth antes de publicar de verdade")
    scheduled = body.scheduled_at
    if scheduled and scheduled.tzinfo:
        scheduled = scheduled.astimezone(timezone.utc).replace(tzinfo=None)
    publication = Publication(
        project_id=project_id,
        render_id=render.id,
        connection_id=connection.id,
        title=body.title,
        description=with_credits(body.description, credits_for(db, render.script_version_id)),
        live=body.live,
        status="scheduled" if scheduled and scheduled > utcnow() else "publishing",
        idempotency_key=key,
        scheduled_at=scheduled,
    )
    db.add(publication)
    db.flush()
    audit(db, project_id, "publication.requested", publication, ctx.actor, live=body.live, scheduled=bool(scheduled))
    db.commit()
    if publication.status == "scheduled":
        return publication
    return run_publication(db, publication, storage, ctx.actor)


@router.get("/projects/{project_id}/publications", response_model=list[PublicationOut])
def list_publications(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(
        db.scalars(select(Publication).where(Publication.project_id == project_id).order_by(Publication.id.desc()))
    )


@router.post("/publications/{publication_id}/run", response_model=PublicationOut)
def run_now(publication_id: int, ctx: EditorContext, db: DbSession, storage: Storage = Depends(get_storage)):
    publication = require_publication(db, ctx, publication_id)
    if publication.status not in {"scheduled", "failed"}:
        raise HTTPException(409, "Apenas publicações agendadas ou com falha podem ser executadas")
    publication.status = "publishing"
    db.commit()
    return run_publication(db, publication, storage, ctx.actor)


@router.delete("/publications/{publication_id}", status_code=204)
def cancel_publication(publication_id: int, ctx: EditorContext, db: DbSession):
    publication = require_publication(db, ctx, publication_id)
    if publication.status != "scheduled":
        raise HTTPException(409, "Apenas publicações agendadas podem ser canceladas")
    publication.status = "cancelled"
    audit(db, publication.project_id, "publication.cancelled", publication, ctx.actor)
    db.commit()


@router.post("/publications/{publication_id}/reconcile", response_model=PublicationOut)
def reconcile_publication(publication_id: int, ctx: EditorContext, db: DbSession):
    publication = require_publication(db, ctx, publication_id)
    if publication.simulated or not publication.external_id:
        raise HTTPException(409, "É necessária uma publicação real")
    connection = db.get(ChannelConnection, publication.connection_id)
    token = access_token_for(connection, OAuthService(get_settings())) if connection else None
    if not token:
        raise HTTPException(409, "Credenciais OAuth são necessárias")
    try:
        publication.status = publication_status(connection.platform, token, publication.external_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Falha ao consultar status: {exc}")
    if publication.status == "published" and not publication.published_at:
        publication.published_at = utcnow()
    audit(db, publication.project_id, "publication.reconciled", publication, ctx.actor, status=publication.status)
    db.commit()
    return publication
