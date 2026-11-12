from datetime import datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import CurrentContext, EditorContext, OwnerContext
from ..channels import OAUTH_PLATFORMS, credential_row, live_allowed, oauth_client, token_fields
from ..config import get_settings
from ..deps import DbSession, audit, require_project
from ..models import ChannelAccount, ChannelConnection, Organization, PlatformCredential, Project
from ..oauth import CONSOLES, OAuthService
from ..schemas import (
    ChannelAccountOut,
    ConnectionCreate,
    ConnectionOut,
    OAuthCallback,
    PlatformCredentialOut,
    PlatformCredentialUpdate,
)
from .projects import connection_out

router = APIRouter(tags=["connections"])


def oauth_service() -> OAuthService:
    return OAuthService(get_settings())


def _require_oauth_platform(platform: str) -> None:
    if platform not in OAUTH_PLATFORMS:
        raise HTTPException(404, "Plataforma sem login OAuth")


@router.get("/platforms")
def platforms(ctx: CurrentContext, db: DbSession):
    service = oauth_service()
    items = []
    for platform, label in OAUTH_PLATFORMS.items():
        accounts = db.scalar(
            select(func.count()).where(
                ChannelAccount.organization_id == ctx.organization.id,
                ChannelAccount.platform == platform,
                ChannelAccount.enabled.is_(True),
            )
        )
        items.append(
            {
                "id": platform,
                "label": label,
                "live_supported": True,
                "oauth_configured": oauth_client(db, ctx.organization.id, platform, service) is not None,
                "live_enabled": live_allowed(db, ctx.organization.id, platform, service.settings),
                "accounts": accounts or 0,
            }
        )
    items.append(
        {"id": "local", "label": "Exportação local", "live_supported": False, "oauth_configured": False, "live_enabled": False, "accounts": 0}
    )
    return items


def _credential_out(db: Session, organization_id: int, platform: str, service: OAuthService) -> PlatformCredentialOut:
    row = credential_row(db, organization_id, platform)
    client = oauth_client(db, organization_id, platform, service)
    return PlatformCredentialOut(
        platform=platform,
        label=OAUTH_PLATFORMS[platform],
        client_id=client.client_id if client else (row.client_id if row else ""),
        has_secret=bool(client),
        source=client.source if client else "none",
        live_enabled=bool(row and row.live_enabled),
        live_forced_by_env=service.settings.allow_live_publish,
        redirect_uri=service.redirect_uri(platform),
        console_url=CONSOLES[platform],
        updated_by=row.updated_by if row else "",
        updated_at=row.updated_at if row else None,
    )


@router.get("/platform-credentials", response_model=list[PlatformCredentialOut])
def list_platform_credentials(ctx: CurrentContext, db: DbSession):
    service = oauth_service()
    return [_credential_out(db, ctx.organization.id, platform, service) for platform in OAUTH_PLATFORMS]


@router.put("/platform-credentials/{platform}", response_model=PlatformCredentialOut)
def save_platform_credentials(platform: str, body: PlatformCredentialUpdate, ctx: OwnerContext, db: DbSession):
    _require_oauth_platform(platform)
    service = oauth_service()
    row = credential_row(db, ctx.organization.id, platform)
    changed_client = not row or row.client_id != body.client_id
    if not body.client_secret and (changed_client or not row.client_secret_encrypted):
        raise HTTPException(422, "Informe o client secret ao cadastrar ou trocar o client ID")
    if not row:
        row = PlatformCredential(organization_id=ctx.organization.id, platform=platform)
        db.add(row)
    row.client_id = body.client_id
    if body.client_secret:
        row.client_secret_encrypted = service.encrypt(body.client_secret)
    row.live_enabled = body.live_enabled
    row.updated_by = ctx.actor
    db.flush()
    audit(db, None, "platform.credentials_saved", row, ctx.actor, platform=platform, live_enabled=body.live_enabled)
    db.commit()
    return _credential_out(db, ctx.organization.id, platform, service)


@router.delete("/platform-credentials/{platform}", status_code=204)
def delete_platform_credentials(platform: str, ctx: OwnerContext, db: DbSession):
    _require_oauth_platform(platform)
    row = credential_row(db, ctx.organization.id, platform)
    if row:
        audit(db, None, "platform.credentials_removed", row, ctx.actor, platform=platform)
        db.delete(row)
        db.commit()


def _account_out(db: Session, account: ChannelAccount) -> ChannelAccountOut:
    config = account.config or {}
    expires_at = config.get("expires_at")
    projects = db.scalar(
        select(func.count()).where(ChannelConnection.account_id == account.id, ChannelConnection.enabled.is_(True))
    )
    return ChannelAccountOut(
        id=account.id,
        platform=account.platform,
        external_account_id=account.external_account_id,
        display_name=account.display_name,
        enabled=account.enabled,
        authorized=account.enabled and bool(config.get("access_token_encrypted")),
        can_refresh=bool(config.get("refresh_token_encrypted")),
        expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        projects=projects or 0,
        updated_at=account.updated_at,
    )


@router.get("/channel-accounts", response_model=list[ChannelAccountOut])
def list_channel_accounts(ctx: CurrentContext, db: DbSession):
    accounts = db.scalars(
        select(ChannelAccount)
        .where(ChannelAccount.organization_id == ctx.organization.id, ChannelAccount.enabled.is_(True))
        .order_by(ChannelAccount.platform, ChannelAccount.id)
    )
    return [_account_out(db, account) for account in accounts]


@router.delete("/channel-accounts/{account_id}", status_code=204)
def disconnect_channel_account(account_id: int, ctx: OwnerContext, db: DbSession):
    account = db.get(ChannelAccount, account_id)
    if not account or account.organization_id != ctx.organization.id:
        raise HTTPException(404, "Conta não encontrada")
    account.enabled = False
    account.config = {}
    audit(db, None, "channel_account.disconnected", account, ctx.actor, platform=account.platform)
    db.commit()


@router.get("/projects/{project_id}/connections", response_model=list[ConnectionOut])
def list_connections(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return [
        connection_out(item)
        for item in db.scalars(
            select(ChannelConnection).where(ChannelConnection.project_id == project_id).order_by(ChannelConnection.id)
        )
    ]


def _link_account(db: Session, project_id: int, account: ChannelAccount) -> ChannelConnection:
    connection = db.scalar(
        select(ChannelConnection).where(
            ChannelConnection.project_id == project_id,
            ChannelConnection.platform == account.platform,
            ChannelConnection.external_account_id == account.external_account_id,
        )
    )
    if connection is None:
        connection = ChannelConnection(
            project_id=project_id, platform=account.platform, external_account_id=account.external_account_id
        )
        db.add(connection)
    connection.account_id = account.id
    connection.enabled = True
    connection.config = {}
    db.flush()
    return connection


@router.post("/projects/{project_id}/connections", response_model=ConnectionOut, status_code=201)
def create_connection(project_id: int, body: ConnectionCreate, ctx: EditorContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    if {"access_token", "refresh_token", "access_token_encrypted", "refresh_token_encrypted"} & set(body.config):
        raise HTTPException(422, "Credenciais devem ser conectadas via OAuth")
    if body.account_id is not None:
        account = db.get(ChannelAccount, body.account_id)
        if not account or account.organization_id != project.organization_id or not account.enabled:
            raise HTTPException(404, "Conta não encontrada")
        connection = _link_account(db, project_id, account)
        audit(db, project_id, "connection.linked", connection, ctx.actor, platform=account.platform, account_id=account.id)
        db.commit()
        return connection_out(connection)
    if not body.external_account_id.strip():
        raise HTTPException(422, "Informe o identificador do canal ou uma conta conectada")
    connection = ChannelConnection(project_id=project_id, **body.model_dump(exclude={"account_id"}))
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
def oauth_authorize(platform: str, ctx: EditorContext, db: DbSession, project_id: int | None = None):
    _require_oauth_platform(platform)
    if project_id is not None:
        require_project(db, ctx, project_id)
    service = oauth_service()
    client = oauth_client(db, ctx.organization.id, platform, service)
    if client is None:
        raise HTTPException(409, f"Login do {OAUTH_PLATFORMS[platform]} não configurado: cadastre o app em Configurações > Plataformas")
    return {"authorization_url": service.authorization_url(platform, client, ctx.organization.id, project_id)}


def complete_oauth(db: Session, body: OAuthCallback) -> tuple[ChannelAccount, ChannelConnection | None]:
    service = oauth_service()
    try:
        organization_id, project_id = service.verify_state(body.state, body.platform)
        if not db.get(Organization, organization_id):
            raise ValueError("Organização não encontrada")
        project = db.get(Project, project_id) if project_id is not None else None
        if project_id is not None and (not project or project.organization_id != organization_id):
            raise ValueError("Projeto não encontrado")
        client = oauth_client(db, organization_id, body.platform, service)
        if client is None:
            raise ValueError("Login OAuth não configurado para esta plataforma")
        token_data = service.exchange(body.platform, body.code, client)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Falha na troca OAuth: {exc}")
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(502, "O provedor OAuth não retornou um access token")
    profile_id, display_name = service.profile(body.platform, access_token)
    external_id = token_data.get("open_id") or profile_id or f"{body.platform}-authorized"
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.organization_id == organization_id,
            ChannelAccount.platform == body.platform,
            ChannelAccount.external_account_id == external_id,
        )
    )
    if account is None:
        account = ChannelAccount(organization_id=organization_id, platform=body.platform, external_account_id=external_id)
        db.add(account)
    previous = account.config if account.enabled else {}
    account.config = token_fields(service, token_data, previous or {})
    account.display_name = display_name or account.display_name or ""
    account.enabled = True
    db.flush()
    connection = _link_account(db, project_id, account) if project_id is not None else None
    audit(db, project_id, "oauth.connected", connection or account, "oauth", platform=body.platform, account_id=account.id)
    db.commit()
    return account, connection


@router.post("/oauth/callback", status_code=201)
def oauth_callback(body: OAuthCallback, db: DbSession):
    account, connection = complete_oauth(db, body)
    return {
        "id": connection.id if connection else None,
        "account_id": account.id,
        "platform": account.platform,
        "connected": True,
    }


def _origin_project(state: str, platform: str) -> int | None:
    try:
        return oauth_service().verify_state(state, platform)[1]
    except (ValueError, KeyError):
        return None


@router.get("/oauth/callback/{platform}")
def oauth_callback_redirect(platform: str, db: DbSession, code: str = "", state: str = "", error: str = ""):
    web = get_settings().web_base_url.rstrip("/")
    project_id = _origin_project(state, platform)
    failure_page = f"{web}/projects" if project_id is not None else f"{web}/settings"
    if error or not code:
        return RedirectResponse(f"{failure_page}?{urlencode({'oauth_error': error or 'cancelado'})}")
    try:
        _, connection = complete_oauth(db, OAuthCallback(platform=platform, code=code, state=state))
    except HTTPException as exc:
        return RedirectResponse(f"{failure_page}?{urlencode({'oauth_error': exc.detail})}")
    if connection is None:
        return RedirectResponse(f"{web}/settings?{urlencode({'connected': platform})}")
    query = urlencode({"tab": "publicacao", "connected": platform})
    return RedirectResponse(f"{web}/projects/{connection.project_id}?{query}")
