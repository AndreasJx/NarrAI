from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select

from ..adapters import KOKORO_VOICES, VOICE_LANGUAGE
from ..auth import CurrentContext, OwnerContext, hash_password
from ..deps import DbSession, audit
from ..models import Membership, User
from ..schemas import MemberCreate, MemberOut, MemberUpdate, OrganizationOut, OrganizationUpdate, VoiceOut
from ..storage import LocalStorage, Storage, get_storage

router = APIRouter(tags=["organization"])


def member_out(membership: Membership, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.get("/organization", response_model=OrganizationOut)
def get_organization(ctx: CurrentContext):
    return ctx.organization


@router.patch("/organization", response_model=OrganizationOut)
def update_organization(body: OrganizationUpdate, ctx: OwnerContext, db: DbSession):
    organization = ctx.organization
    if body.voice is not None and body.voice not in VOICE_LANGUAGE:
        raise HTTPException(422, "Voz não suportada")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(organization, key, value)
    if body.voice is not None:
        organization.voices = {**(organization.voices or {}), VOICE_LANGUAGE[body.voice]: body.voice}
    audit(db, None, "organization.updated", organization, ctx.actor, **body.model_dump(exclude_none=True))
    db.commit()
    return organization


@router.get("/voices", response_model=list[VoiceOut])
def voices(_: CurrentContext, storage: Storage = Depends(get_storage)):
    return [{**voice, "sample_available": storage.head(f"voices/{voice['id']}.wav") is not None} for voice in KOKORO_VOICES]


def _voice_key(voice_id: str) -> str:
    if voice_id not in {voice["id"] for voice in KOKORO_VOICES}:
        raise HTTPException(404, "Voz não encontrada")
    return f"voices/{voice_id}.wav"


@router.get("/voices/{voice_id}/sample")
def voice_sample(voice_id: str, _: CurrentContext, storage: Storage = Depends(get_storage)):
    key = _voice_key(voice_id)
    if storage.head(key) is None:
        raise HTTPException(404, "Amostra ainda não gerada pelo worker")
    if isinstance(storage, LocalStorage):
        return FileResponse(storage.path(key), media_type="audio/wav")
    return RedirectResponse(storage.presign_get(key, "audio/wav"))


@router.get("/organization/members", response_model=list[MemberOut])
def list_members(ctx: CurrentContext, db: DbSession):
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == ctx.organization.id)
        .order_by(User.name)
    )
    return [member_out(membership, user) for membership, user in rows]


@router.post("/organization/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberCreate, ctx: OwnerContext, db: DbSession):
    user = db.scalar(select(User).where(User.email == body.email))
    if not user:
        if not body.password:
            raise HTTPException(422, "Defina uma senha inicial para o novo usuário")
        user = User(email=body.email, name=body.name, password_hash=hash_password(body.password))
        db.add(user)
        db.flush()
    existing = db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.organization_id == ctx.organization.id)
    )
    if existing:
        raise HTTPException(409, "Usuário já é membro desta organização")
    membership = Membership(user_id=user.id, organization_id=ctx.organization.id, role=body.role)
    db.add(membership)
    db.flush()
    audit(db, None, "member.added", membership, ctx.actor, email=user.email, role=body.role)
    db.commit()
    return member_out(membership, user)


def _membership(db: DbSession, organization_id: int, user_id: int) -> Membership:
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user_id, Membership.organization_id == organization_id)
    )
    if not membership:
        raise HTTPException(404, "Membro não encontrado")
    return membership


def _ensure_other_owner(db: DbSession, organization_id: int) -> None:
    owners = db.scalar(
        select(func.count()).where(Membership.organization_id == organization_id, Membership.role == "owner")
    )
    if owners <= 1:
        raise HTTPException(409, "A organização precisa de pelo menos um proprietário")


@router.patch("/organization/members/{user_id}", response_model=MemberOut)
def update_member(user_id: int, body: MemberUpdate, ctx: OwnerContext, db: DbSession):
    membership = _membership(db, ctx.organization.id, user_id)
    if membership.role == "owner" and body.role != "owner":
        _ensure_other_owner(db, ctx.organization.id)
    membership.role = body.role
    audit(db, None, "member.role_changed", membership, ctx.actor, role=body.role)
    db.commit()
    return member_out(membership, db.get(User, user_id))


@router.delete("/organization/members/{user_id}", status_code=204)
def remove_member(user_id: int, ctx: OwnerContext, db: DbSession):
    membership = _membership(db, ctx.organization.id, user_id)
    if membership.role == "owner":
        _ensure_other_owner(db, ctx.organization.id)
    audit(db, None, "member.removed", membership, ctx.actor, user_id=user_id)
    db.delete(membership)
    db.commit()
