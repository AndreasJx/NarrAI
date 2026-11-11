from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..auth import CurrentContext, EditorContext
from ..deps import DbSession, require_project
from ..jobs import enqueue
from ..models import Scene, ScriptVersion
from ..production import produce_media
from ..retention import credits_for, shots_for
from ..schemas import ShotOut
from ..storage import Storage, get_storage

router = APIRouter(tags=["media"])


def require_script(db: DbSession, project_id: int, script_version_id: int) -> ScriptVersion:
    script = db.get(ScriptVersion, script_version_id)
    if not script or script.project_id != project_id:
        raise HTTPException(404, "Versão de roteiro não encontrada")
    return script


@router.post("/projects/{project_id}/media/auto", status_code=202)
def auto_media(
    project_id: int,
    script_version_id: int,
    ctx: EditorContext,
    db: DbSession,
    storage: Storage = Depends(get_storage),
):
    project = require_project(db, ctx, project_id)
    script = require_script(db, project_id, script_version_id)
    if enqueue({"type": "media", "project_id": project.id, "script_version_id": script.id, "actor": ctx.actor}):
        return {"queued": True}
    summary, _ = produce_media(db, project, script, storage, ctx.actor)
    db.commit()
    return {"queued": False, **summary.__dict__}


@router.get("/projects/{project_id}/shots", response_model=list[ShotOut])
def list_shots(project_id: int, script_version_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    require_script(db, project_id, script_version_id)
    scene_ids = list(db.scalars(select(Scene.id).where(Scene.script_version_id == script_version_id)))
    return [shot for shots in shots_for(db, scene_ids).values() for shot in shots]


@router.get("/projects/{project_id}/credits")
def list_credits(project_id: int, script_version_id: int, ctx: CurrentContext, db: DbSession) -> list[str]:
    require_project(db, ctx, project_id)
    require_script(db, project_id, script_version_id)
    return credits_for(db, script_version_id)
