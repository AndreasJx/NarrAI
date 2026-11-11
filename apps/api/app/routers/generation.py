from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from video_ai_contracts import ProjectStatus

from ..ai import get_ai
from ..auth import CurrentContext, EditorContext
from ..config import get_settings
from ..deps import DbSession, audit, require_budget, require_project, set_status
from ..jobs import enqueue
from ..learning import playbook_context
from ..models import Brief, Project, ResearchDossier, Scene, ScriptVersion, Source
from ..research import run_research
from ..schemas import DossierOut, GenerationRequest, SceneOut, ScriptOut, SourceOut
from ..writer import write_script

router = APIRouter(tags=["generation"])


def require_brief(db: Session, project_id: int) -> Brief:
    brief = db.scalar(select(Brief).where(Brief.project_id == project_id).order_by(Brief.id.desc()))
    if not brief:
        raise HTTPException(409, "O briefing é obrigatório")
    return brief


def latest_dossier(db: Session, project_id: int) -> ResearchDossier | None:
    return db.scalar(select(ResearchDossier).where(ResearchDossier.project_id == project_id).order_by(ResearchDossier.id.desc()))


def estimate_duration(text: str) -> float:
    words = len(text.split())
    return round(max(3.0, min(30.0, words / 2.6 + 0.8)), 1)


def ensure_storyboard(db: Session, script: ScriptVersion) -> list[Scene]:
    existing = list(db.scalars(select(Scene).where(Scene.script_version_id == script.id).order_by(Scene.position)))
    if existing:
        return existing
    parts = [part.strip() for part in script.content.split("\n") if part.strip()]
    scenes = [
        Scene(
            script_version_id=script.id,
            position=index,
            narration=part,
            visual_prompt=f"Vertical cinematic scene illustrating: {part[:120]}",
            duration_seconds=estimate_duration(part),
        )
        for index, part in enumerate(parts, 1)
    ]
    db.add_all(scenes)
    db.flush()
    return scenes


def research_project(db: Session, project: Project, actor: str, estimate: int = 0) -> ResearchDossier:
    brief = require_brief(db, project.id)
    require_budget(project, estimate)
    outcome = run_research(db, project, brief, get_settings(), get_ai())
    charged = outcome.cost_cents or estimate
    project.spent_cents += charged
    audit(
        db,
        project.id,
        "research.generated",
        outcome.dossier,
        actor,
        cost_cents=charged,
        provider=outcome.dossier.provider,
        articles=sum(1 for source in outcome.sources if source.provider == "tavily"),
        videos=len(outcome.videos),
    )
    return outcome.dossier


def script_project(db: Session, project: Project, actor: str, estimate: int = 0, feedback: str = "") -> ScriptVersion:
    brief = require_brief(db, project.id)
    require_budget(project, estimate)
    constraints = brief.constraints or {}
    playbook = playbook_context(db, project.organization_id).text
    if feedback:
        playbook = f"{playbook}\nCorrija os problemas apontados na revisão anterior:\n{feedback}".strip()
    draft = write_script(
        get_ai(),
        topic=brief.topic,
        audience=brief.audience,
        objective=brief.objective,
        language=brief.language or project.language,
        duration_seconds=int(constraints.get("duration_seconds", 60)),
        tone=str(constraints.get("tone", "didático e próximo")),
        dossier=latest_dossier(db, project.id),
        playbook=playbook,
    )
    version = (db.scalar(select(func.max(ScriptVersion.version)).where(ScriptVersion.project_id == project.id)) or 0) + 1
    charged = draft.cost_cents or estimate
    script = ScriptVersion(
        project_id=project.id,
        version=version,
        content=draft.content,
        estimated_cost_cents=charged,
        author=draft.author,
        metadata_json=draft.metadata,
    )
    project.spent_cents += charged
    db.add(script)
    db.flush()
    audit(db, project.id, "script.generated", script, actor, cost_cents=charged, provider=draft.author)
    set_status(db, project, ProjectStatus.REVIEW, actor, "roteiro aguardando revisão")
    return script


@router.post("/projects/{project_id}/generate/research", response_model=SourceOut)
def generate_research(project_id: int, body: GenerationRequest, ctx: EditorContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    research_project(db, project, ctx.actor, body.estimated_cost_cents)
    db.commit()
    return db.scalar(select(Source).where(Source.project_id == project_id).order_by(Source.id.desc()))


@router.post("/projects/{project_id}/research/jobs", status_code=202)
def queue_research(project_id: int, ctx: EditorContext, db: DbSession) -> dict[str, bool]:
    project = require_project(db, ctx, project_id)
    require_brief(db, project_id)
    if enqueue({"type": "research", "project_id": project.id, "actor": ctx.actor}):
        audit(db, project_id, "research.queued", project, ctx.actor)
        db.commit()
        return {"queued": True}
    research_project(db, project, ctx.actor)
    db.commit()
    return {"queued": False}


@router.get("/projects/{project_id}/dossier", response_model=DossierOut | None)
def get_dossier(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return latest_dossier(db, project_id)


@router.post("/projects/{project_id}/generate/script", response_model=ScriptOut)
def generate_script(project_id: int, body: GenerationRequest, ctx: EditorContext, db: DbSession):
    project = require_project(db, ctx, project_id)
    script = script_project(db, project, ctx.actor, body.estimated_cost_cents)
    db.commit()
    return script


@router.post("/projects/{project_id}/generate/storyboard", response_model=list[SceneOut])
def generate_storyboard(project_id: int, script_version_id: int, ctx: EditorContext, db: DbSession):
    require_project(db, ctx, project_id)
    script = db.get(ScriptVersion, script_version_id)
    if not script or script.project_id != project_id:
        raise HTTPException(404, "Versão de roteiro não encontrada")
    scenes = ensure_storyboard(db, script)
    audit(db, project_id, "storyboard.generated", script, ctx.actor, scenes=len(scenes))
    db.commit()
    return scenes
