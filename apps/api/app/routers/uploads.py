import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select, update

from ..auth import Context, CurrentContext, EditorContext
from ..config import get_settings
from ..deps import DbSession, audit, require_project
from ..models import Asset, Scene
from ..schemas import AssetOut, PreviewOut, UploadCreate, UploadTicket
from ..storage import ALLOWED_UPLOADS, LocalStorage, Storage, get_storage, signature_matches

router = APIRouter(tags=["uploads"])


def require_asset(db: DbSession, ctx: Context, asset_id: int) -> Asset:
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Arquivo não encontrado")
    require_project(db, ctx, asset.project_id)
    return asset


@router.post("/projects/{project_id}/uploads", response_model=UploadTicket, status_code=201)
def create_upload(
    project_id: int,
    body: UploadCreate,
    ctx: EditorContext,
    db: DbSession,
    storage: Storage = Depends(get_storage),
):
    project = require_project(db, ctx, project_id)
    if body.content_type not in ALLOWED_UPLOADS:
        raise HTTPException(422, "Formato não suportado. Envie JPG, PNG, WEBP, MP4, MOV ou WEBM.")
    max_bytes = get_settings().upload_max_bytes
    if body.size_bytes > max_bytes:
        raise HTTPException(413, f"Arquivo excede o limite de {max_bytes // (1024 * 1024)} MiB")
    kind, extension, _ = ALLOWED_UPLOADS[body.content_type]
    key = f"orgs/{project.organization_id}/projects/{project.id}/uploads/{uuid.uuid4().hex}{extension}"
    asset = Asset(
        project_id=project.id,
        kind=kind,
        uri=key,
        filename=body.filename[:300],
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        status="pending",
        metadata_json={"source": "upload", "uploaded_by": ctx.actor},
    )
    db.add(asset)
    db.flush()
    audit(db, project.id, "upload.requested", asset, ctx.actor, content_type=body.content_type, size=body.size_bytes)
    db.commit()
    url = storage.presign_put(key, body.content_type) or f"/api/v1/uploads/{asset.id}/content"
    return UploadTicket(asset=AssetOut.model_validate(asset), upload_url=url, headers={"Content-Type": body.content_type})


@router.put("/uploads/{asset_id}/content", status_code=204)
async def upload_content(
    asset_id: int,
    request: Request,
    ctx: EditorContext,
    db: DbSession,
    storage: Storage = Depends(get_storage),
):
    asset = require_asset(db, ctx, asset_id)
    if not isinstance(storage, LocalStorage):
        raise HTTPException(409, "Use a URL assinada para enviar este arquivo")
    if asset.status != "pending":
        raise HTTPException(409, "Upload já concluído")
    max_bytes = get_settings().upload_max_bytes
    destination = storage.path(asset.uri)
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with destination.open("wb") as handle:
        async for chunk in request.stream():
            written += len(chunk)
            if written > max_bytes:
                break
            handle.write(chunk)
    if written > max_bytes:
        destination.unlink(missing_ok=True)
        raise HTTPException(413, "Arquivo excede o limite de upload")


@router.post("/uploads/{asset_id}/complete", response_model=AssetOut)
def complete_upload(asset_id: int, ctx: EditorContext, db: DbSession, storage: Storage = Depends(get_storage)):
    asset = require_asset(db, ctx, asset_id)
    if asset.status == "ready":
        return asset
    size = storage.head(asset.uri)
    if size is None:
        raise HTTPException(409, "Arquivo ainda não recebido pelo armazenamento")
    rejection = None
    if size > get_settings().upload_max_bytes:
        rejection = "Arquivo excede o limite de upload"
    elif not signature_matches(asset.content_type or "", storage.read_prefix(asset.uri, 32)):
        rejection = "O conteúdo do arquivo não corresponde ao formato declarado"
    if rejection:
        storage.delete(asset.uri)
        asset.status = "rejected"
        audit(db, asset.project_id, "upload.rejected", asset, ctx.actor, reason=rejection)
        db.commit()
        raise HTTPException(422, rejection)
    asset.status, asset.size_bytes = "ready", size
    audit(db, asset.project_id, "upload.completed", asset, ctx.actor, size=size)
    db.commit()
    return asset


@router.get("/projects/{project_id}/assets", response_model=list[AssetOut])
def list_assets(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(db.scalars(select(Asset).where(Asset.project_id == project_id).order_by(Asset.id.desc())))


@router.get("/assets/{asset_id}/url", response_model=PreviewOut)
def asset_url(asset_id: int, ctx: CurrentContext, db: DbSession, storage: Storage = Depends(get_storage)):
    asset = require_asset(db, ctx, asset_id)
    if asset.status != "ready":
        raise HTTPException(409, "Arquivo indisponível")
    url = storage.presign_get(asset.uri, asset.content_type) or f"/api/v1/assets/{asset.id}/content"
    return PreviewOut(url=url, kind=asset.kind)


@router.get("/assets/{asset_id}/content")
def asset_content(asset_id: int, ctx: CurrentContext, db: DbSession, storage: Storage = Depends(get_storage)):
    asset = require_asset(db, ctx, asset_id)
    if asset.status != "ready":
        raise HTTPException(409, "Arquivo indisponível")
    if isinstance(storage, LocalStorage):
        return FileResponse(storage.path(asset.uri), media_type=asset.content_type or "application/octet-stream")
    return RedirectResponse(storage.presign_get(asset.uri, asset.content_type))


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: int, ctx: EditorContext, db: DbSession, storage: Storage = Depends(get_storage)):
    asset = require_asset(db, ctx, asset_id)
    if asset.kind not in {"image", "video"}:
        raise HTTPException(409, "Apenas mídias enviadas podem ser removidas")
    db.execute(update(Scene).where(Scene.media_asset_id == asset.id).values(media_asset_id=None))
    if asset.status == "ready":
        storage.delete(asset.uri)
    audit(db, asset.project_id, "asset.deleted", asset, ctx.actor)
    db.delete(asset)
    db.commit()
