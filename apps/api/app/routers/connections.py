from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import CurrentContext, EditorContext
from ..config import get_settings
from ..deps import DbSession, audit, require_project
from ..models import ChannelConnection, Project
from ..oauth import OAuthService
from ..schemas import ConnectionCreate, ConnectionOut, OAuthCallback
from .projects import connection_out

router = APIRouter(tags=["connections"])


def oauth_service() -> OAuthService:
    return OAuthService(get_settings())


@router.get("/platforms")
def platforms(_: CurrentContext):
    settings = get_settings()
    return [
        {
            "id": "youtube",
            "label": "YouTube Shorts",
            "live_supported": True,
            "oauth_configured": bool(settings.youtube_client_id and settings.youtube_client_secret),
            "live_enabled": settings.allow_live_publish,
        },
        {
            "id": "tiktok",
            "label": "TikTok",
            "live_supported": True,
            "oauth_configured": bool(settings.tiktok_client_key and settings.tiktok_client_secret),
            "live_enabled": settings.allow_live_publish,
        },
        {"id": "local", "label": "Exportação local", "live_supported": False, "oauth_configured": False, "live_enabled": False},
    ]


@router.get("/projects/{project_id}/connections", response_model=list[ConnectionOut])
def list_connections(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return [
        connection_out(item)
        for item in db.scalars(
            select(ChannelConnection).where(ChannelConnection.project_id == project_id).order_by(ChannelConnection.id)
        )
    ]


@router.post("/projects/{project_id}/connections", response_model=ConnectionOut, status_code=201)
def create_connection(project_id: int, body: ConnectionCreate, ctx: EditorContext, db: DbSession):
    require_project(db, ctx, project_id)
    if {"access_token", "refresh_token", "access_token_encrypted", "refresh_token_encrypted"} & set(body.config):
        raise HTTPException(422, "Credenciais devem ser conectadas via OAuth")
    connection = ChannelConnection(project_id=project_id, **body.model_dump())
    db.add(connection)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conexão já existe")
    audit(db, project_id, "connection.created", connection, ctx.actor, platform=body.platform)
    db.commit()
    return connection_out(connection)


@router.delete("/connections/{connection_id}", status_code=204)
def disable_connection(connection_id: int, ctx: EditorContext, db: DbSession):
    connection = db.get(ChannelConnection, connection_id)
    if not connection:
        raise HTTPException(404, "Conexão não encontrada")
    require_project(db, ctx, connection.project_id)
    connection.enabled = False
    connection.config = {}
    audit(db, connection.project_id, "connection.disabled", connection, ctx.actor)
    db.commit()


@router.get("/platforms/{platform}/oauth/authorize")
def oauth_authorize(platform: str, project_id: int, ctx: EditorContext, db: DbSession):
    require_project(db, ctx, project_id)
    try:
        return {"authorization_url": oauth_service().authorization_url(platform, project_id)}
    except ValueError as exc:
        raise HTTPException(409, str(exc))


def complete_oauth(db: Session, body: OAuthCallback) -> ChannelConnection:
    service = oauth_service()
    try:
        project_id = service.verify_state(body.state, body.platform)
        if not db.get(Project, project_id):
            raise ValueError("Projeto não encontrado")
        token_data = service.exchange(body.platform, body.code)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Falha na troca OAuth: {exc}")
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(502, "O provedor OAuth não retornou um access token")
    external_id = token_data.get("open_id") or f"{body.platform}-authorized"
    connection = db.scalar(
        select(ChannelConnection).where(
            ChannelConnection.project_id == project_id,
            ChannelConnection.platform == body.platform,
            ChannelConnection.external_account_id == external_id,
        )
    )
    secret_config = {
        "access_token_encrypted": service.encrypt(access_token),
        "refresh_token_encrypted": service.encrypt(token_data["refresh_token"])
        if token_data.get("refresh_token")
        else None,
        "expires_in": token_data.get("expires_in"),
        "scope": token_data.get("scope"),
    }
    if connection:
        connection.config = secret_config
        connection.enabled = True
    else:
        connection = ChannelConnection(
            project_id=project_id,
            platform=body.platform,
            external_account_id=external_id,
            enabled=True,
            config=secret_config,
        )
        db.add(connection)
    db.flush()
    audit(db, project_id, "oauth.connected", connection, "oauth", platform=body.platform)
    db.commit()
    return connection


@router.post("/oauth/callback", status_code=201)
def oauth_callback(body: OAuthCallback, db: DbSession):
    connection = complete_oauth(db, body)
    return {"id": connection.id, "platform": connection.platform, "connected": True}


@router.get("/oauth/callback/{platform}")
def oauth_callback_redirect(platform: str, db: DbSession, code: str = "", state: str = "", error: str = ""):
    web = get_settings().web_base_url.rstrip("/")
    if error or not code:
        return RedirectResponse(f"{web}/projects?{urlencode({'oauth_error': error or 'cancelado'})}")
    try:
        connection = complete_oauth(db, OAuthCallback(platform=platform, code=code, state=state))
    except HTTPException as exc:
        return RedirectResponse(f"{web}/projects?{urlencode({'oauth_error': exc.detail})}")
    query = urlencode({"tab": "publicacao", "connected": platform})
    return RedirectResponse(f"{web}/projects/{connection.project_id}?{query}")
