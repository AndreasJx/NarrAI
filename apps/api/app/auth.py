from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import Membership, Organization, User

ROLES = ("owner", "editor", "viewer")
password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hasher.verify(password, hashed)


def issue_token(user_id: int, organization_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org": organization_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.jwt_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(get_settings().session_cookie, path="/")


@dataclass
class Context:
    user: User
    organization: Organization
    role: str

    @property
    def actor(self) -> str:
        return self.user.email


def _token_from(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:]
    return request.cookies.get(get_settings().session_cookie)


def current_context(request: Request, db: Session = Depends(get_db)) -> Context:
    token = _token_from(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticação necessária")
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        user_id, organization_id = int(payload["sub"]), int(payload["org"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada") from exc
    user = db.get(User, user_id)
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user_id, Membership.organization_id == organization_id)
    )
    if not user or not user.active or not membership:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")
    return Context(user=user, organization=db.get(Organization, organization_id), role=membership.role)


CurrentContext = Annotated[Context, Depends(current_context)]


def require_role(*roles: str):
    def dependency(ctx: CurrentContext) -> Context:
        if ctx.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permissão insuficiente para esta ação")
        return ctx

    return dependency


EditorContext = Annotated[Context, Depends(require_role("owner", "editor"))]
OwnerContext = Annotated[Context, Depends(require_role("owner"))]
