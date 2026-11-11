from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    CurrentContext,
    clear_session_cookie,
    hash_password,
    issue_token,
    set_session_cookie,
    verify_password,
)
from ..deps import DbSession
from ..models import Membership, Organization, User
from ..schemas import LoginIn, MeOut, OrganizationOut, SignupIn, SwitchOrganization, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def build_me(db: Session, user: User, organization: Organization, role: str) -> MeOut:
    organizations = db.scalars(
        select(Organization)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    )
    return MeOut(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(organization),
        role=role,
        organizations=[OrganizationOut.model_validate(item) for item in organizations],
    )


@router.post("/signup", response_model=MeOut, status_code=201)
def signup(body: SignupIn, response: Response, db: DbSession):
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(409, "Já existe uma conta com este e-mail")
    organization = Organization(name=body.organization_name)
    user = User(email=body.email, name=body.name, password_hash=hash_password(body.password))
    db.add_all([organization, user])
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=organization.id, role="owner"))
    db.commit()
    set_session_cookie(response, issue_token(user.id, organization.id))
    return build_me(db, user, organization, "owner")


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, response: Response, db: DbSession):
    user = db.scalar(select(User).where(User.email == body.email))
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha inválidos")
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id))
    if not membership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário sem organização")
    organization = db.get(Organization, membership.organization_id)
    set_session_cookie(response, issue_token(user.id, organization.id))
    return build_me(db, user, organization, membership.role)


@router.post("/logout", status_code=204)
def logout():
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=MeOut)
def me(ctx: CurrentContext, db: DbSession):
    return build_me(db, ctx.user, ctx.organization, ctx.role)


@router.post("/switch-organization", response_model=MeOut)
def switch_organization(body: SwitchOrganization, ctx: CurrentContext, response: Response, db: DbSession):
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == ctx.user.id,
            Membership.organization_id == body.organization_id,
        )
    )
    if not membership:
        raise HTTPException(404, "Organização não encontrada")
    organization = db.get(Organization, membership.organization_id)
    set_session_cookie(response, issue_token(ctx.user.id, organization.id))
    return build_me(db, ctx.user, organization, membership.role)
