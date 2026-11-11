from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from video_ai_contracts import ProjectStatus

from .auth import Context
from .database import get_db
from .models import Approval, AuditEvent, Project

DbSession = Annotated[Session, Depends(get_db)]


def as_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.key) for column in row.__table__.columns}


def require_project(db: Session, ctx: Context, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project or project.organization_id != ctx.organization.id:
        raise HTTPException(404, "Projeto não encontrado")
    return project


def require_budget(project: Project, amount: int) -> None:
    if project.spent_cents + amount > project.budget_cents:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "Orçamento do projeto excedido")


def approved(db: Session, project_id: int, gate: str, target_id: int) -> bool:
    value = db.scalar(
        select(Approval.approved).where(
            Approval.project_id == project_id,
            Approval.gate == gate,
            Approval.target_id == target_id,
        )
    )
    return value is True


def audit(db: Session, project_id: int | None, action: str, entity: Any, actor: str = "system", **payload: Any) -> None:
    db.add(
        AuditEvent(
            project_id=project_id,
            action=action,
            actor=actor,
            entity_type=entity.__class__.__name__,
            entity_id=getattr(entity, "id", None),
            payload=payload,
        )
    )


def set_status(db: Session, project: Project, new_status: ProjectStatus, actor: str, reason: str = "") -> None:
    if project.status == new_status:
        return
    previous = project.status
    project.status = new_status.value
    audit(db, project.id, "project.status_changed", project, actor, previous=previous, current=new_status.value, reason=reason)
