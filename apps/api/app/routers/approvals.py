from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from video_ai_contracts import ProjectStatus

from ..auth import EditorContext
from ..deps import DbSession, audit, require_project, set_status
from ..models import Approval, Render, ScriptVersion
from ..schemas import ApprovalCreate, ApprovalOut

router = APIRouter(tags=["approvals"])


@router.post("/projects/{project_id}/approvals", response_model=ApprovalOut)
def set_approval(project_id: int, body: ApprovalCreate, ctx: EditorContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    if body.gate == "script":
        target = db.get(ScriptVersion, body.target_id)
    else:
        target = db.get(Render, body.target_id)
        if target and body.gate == "publish" and body.approved and target.status != "completed":
            raise HTTPException(409, "Só é possível aprovar a publicação de um render concluído")
    if not target or target.project_id != project_id:
        raise HTTPException(404, "Item a aprovar não encontrado")
    approval = db.scalar(
        select(Approval).where(
            Approval.project_id == project_id,
            Approval.gate == body.gate,
            Approval.target_id == body.target_id,
        )
    )
    if approval:
        approval.approved, approval.actor, approval.note = body.approved, ctx.actor, body.note
    else:
        approval = Approval(project_id=project_id, actor=ctx.actor, **body.model_dump())
        db.add(approval)
    db.flush()
    audit(db, project_id, "approval.set", approval, ctx.actor, gate=body.gate, approved=body.approved)
    if body.approved:
        set_status(db, project, ProjectStatus.APPROVED, ctx.actor, f"aprovação: {body.gate}")
    else:
        set_status(db, project, ProjectStatus.REVIEW, ctx.actor, f"reprovação: {body.gate}")
    db.commit()
    return approval
