import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import ChannelAccount, ChannelConnection, PlatformCredential, Project, utcnow
from .oauth import OAuthClient, OAuthService, env_client

logger = logging.getLogger("narra.channels")

OAUTH_PLATFORMS = {"youtube": "YouTube Shorts", "tiktok": "TikTok"}
REFRESH_MARGIN = timedelta(minutes=2)


def credential_row(db: Session, organization_id: int, platform: str) -> PlatformCredential | None:
    return db.scalar(
        select(PlatformCredential).where(
            PlatformCredential.organization_id == organization_id, PlatformCredential.platform == platform
        )
    )


def oauth_client(db: Session, organization_id: int, platform: str, oauth: OAuthService) -> OAuthClient | None:
    """The organization's own OAuth app wins; the .env values are only a server-wide fallback."""
    row = credential_row(db, organization_id, platform)
    if row and row.client_id and row.client_secret_encrypted:
        try:
            return OAuthClient(row.client_id, oauth.decrypt(row.client_secret_encrypted), "organization")
        except ValueError:
            logger.warning("Client secret of %s for organization %s cannot be decrypted", platform, organization_id)
    return env_client(oauth.settings, platform)


def live_allowed(db: Session, organization_id: int, platform: str, settings: Settings) -> bool:
    if platform not in OAUTH_PLATFORMS:
        return False
    if settings.allow_live_publish:
        return True
    row = credential_row(db, organization_id, platform)
    return bool(row and row.live_enabled)


def token_config(connection: ChannelConnection) -> dict[str, Any]:
    """Tokens live on the shared organization account; legacy connections may still carry their own."""
    if connection.account_id and connection.account:
        return (connection.account.config or {}) if connection.account.enabled else {}
    return connection.config or {}


def is_authorized(connection: ChannelConnection) -> bool:
    return bool(token_config(connection).get("access_token_encrypted"))


def token_fields(oauth: OAuthService, token_data: dict, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = previous or {}
    expires_in = token_data.get("expires_in")
    refresh = token_data.get("refresh_token")
    return {
        **previous,
        "access_token_encrypted": oauth.encrypt(token_data["access_token"]),
        # Google omits the refresh token on refresh responses; keep the one we already have.
        "refresh_token_encrypted": oauth.encrypt(refresh) if refresh else previous.get("refresh_token_encrypted"),
        "expires_at": (utcnow() + timedelta(seconds=int(expires_in))).isoformat() if expires_in else None,
        "scope": token_data.get("scope") or previous.get("scope"),
    }


def _expired(config: dict[str, Any]) -> bool:
    expires_at = config.get("expires_at")
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) - REFRESH_MARGIN <= utcnow()
    except ValueError:
        return True


def access_token_for(db: Session, connection: ChannelConnection | None, settings: Settings) -> str | None:
    """Decrypted access token, refreshed and persisted (caller commits) when it is about to expire."""
    if connection is None:
        return None
    config = token_config(connection)
    encrypted = config.get("access_token_encrypted")
    if not encrypted:
        return None
    oauth = OAuthService(settings)
    if _expired(config) and config.get("refresh_token_encrypted"):
        if connection.account_id and connection.account:
            organization_id = connection.account.organization_id
        else:
            organization_id = db.get(Project, connection.project_id).organization_id
        client = oauth_client(db, organization_id, connection.platform, oauth)
        if client:
            try:
                refreshed = oauth.refresh(connection.platform, oauth.decrypt(config["refresh_token_encrypted"]), client)
                updated = token_fields(oauth, refreshed, config)
                if connection.account_id and connection.account:
                    connection.account.config = updated
                else:
                    connection.config = updated
                db.flush()
                return refreshed["access_token"]
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                logger.warning("Token refresh failed for connection %s: %s", connection.id, exc)
    return oauth.decrypt(encrypted)


def active_account(db: Session, organization_id: int, platform: str) -> ChannelAccount | None:
    return db.scalar(
        select(ChannelAccount)
        .where(
            ChannelAccount.organization_id == organization_id,
            ChannelAccount.platform == platform,
            ChannelAccount.enabled.is_(True),
        )
        .order_by(ChannelAccount.updated_at.desc(), ChannelAccount.id.desc())
    )
