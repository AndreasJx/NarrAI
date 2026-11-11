from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai import get_ai
from .config import get_settings
from .deps import audit, require_budget
from .learning import playbook_context
from .media import source_media
from .models import AutopilotSettings, Brief, Project, ResearchDossier, ScriptVersion
from .retention import ShotPlan, plan_shots
from .storage import Storage


@dataclass
class MediaSummary:
    scenes: int
    scenes_with_media: int
    assets: int
    clips: int
    shots: int
    fair_use_seconds: float
    dropped_clips: int
    candidates: int
    cost_cents: int


def produce_media(db: Session, project: Project, script: ScriptVersion, storage: Storage, actor: str) -> tuple[MediaSummary, ShotPlan]:
    from .routers.generation import ensure_storyboard

    settings = get_settings()
    require_budget(project, 0)
    brief = db.scalar(select(Brief).where(Brief.project_id == project.id).order_by(Brief.id.desc()))
    dossier = db.scalar(select(ResearchDossier).where(ResearchDossier.project_id == project.id).order_by(ResearchDossier.id.desc()))
    autopilot = db.scalar(select(AutopilotSettings).where(AutopilotSettings.organization_id == project.organization_id))
    scenes = ensure_storyboard(db, script)
    outcome = source_media(
        db,
        project,
        scenes,
        storage,
        settings,
        get_ai(settings),
        topic=brief.topic if brief else project.name,
        dossier=dossier,
        press_kit_urls=list(autopilot.press_kit_urls or []) if autopilot else [],
        context=autopilot.niche if autopilot else "",
    )
    plan = plan_shots(
        db,
        scenes,
        outcome.by_scene,
        outcome.clips,
        playbook_context(db, project.organization_id).params,
        settings.fair_use_max_clip_seconds,
        settings.fair_use_max_ratio,
    )
    project.spent_cents += outcome.cost_cents
    summary = MediaSummary(
        scenes=len(scenes),
        scenes_with_media=len(outcome.by_scene),
        assets=sum(len(items) for items in outcome.by_scene.values()),
        clips=len(outcome.clips),
        shots=len(plan.shots),
        fair_use_seconds=round(plan.fair_use_seconds, 1),
        dropped_clips=plan.dropped_clips,
        candidates=outcome.searched,
        cost_cents=outcome.cost_cents,
    )
    audit(db, project.id, "media.sourced", script, actor, **summary.__dict__)
    return summary, plan
