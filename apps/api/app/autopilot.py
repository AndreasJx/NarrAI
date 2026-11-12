import logging
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from video_ai_contracts import ProjectStatus

from .ai import get_ai
from .channels import active_account, is_authorized, live_allowed
from .config import get_settings
from .deps import audit, set_status
from .gates import GateResult, review_render, review_script
from .jobs import enqueue
from .models import (
    Approval,
    AutopilotSettings,
    Brief,
    ChannelConnection,
    Experiment,
    Organization,
    Project,
    Publication,
    Render,
    ResearchDossier,
    ScriptVersion,
    StageRun,
    TopicSuggestion,
    utcnow,
)
from .publishing import execute_publication
from .retention import credits_for, with_credits
from .storage import Storage

logger = logging.getLogger("narra.autopilot")
STAGES = ("research", "script", "script_gate", "media", "render", "render_gate", "publish")
TERMINAL = {"done", "needs_review", "failed", "stopped"}
WAITING = "waiting"
ACTOR = "autopilot"
MAX_REWRITES = 1


class Blocked(Exception):
    """A quality gate (or missing configuration) needs a human decision."""


def settings_for(db: Session, organization_id: int) -> AutopilotSettings:
    config = db.scalar(select(AutopilotSettings).where(AutopilotSettings.organization_id == organization_id))
    if config is None:
        config = AutopilotSettings(organization_id=organization_id, enabled=get_settings().autopilot_default_enabled)
        db.add(config)
        db.flush()
    return config


def create_project(
    db: Session,
    organization: Organization,
    actor: str,
    topic: str,
    *,
    angle: str = "",
    language: str | None = None,
    audience: str | None = None,
    duration_seconds: int | None = None,
    created_by: int | None = None,
    suggestion: TopicSuggestion | None = None,
) -> Project:
    from .learning import playbook_context

    config = settings_for(db, organization.id)
    language = language or config.language
    learned = playbook_context(db, organization.id).params.get("prefer_duration_seconds")
    duration_seconds = duration_seconds or (int(learned) if learned else None)
    project = Project(
        organization_id=organization.id,
        created_by=created_by,
        name=topic.strip()[:60],
        language=language,
        budget_cents=config.video_budget_cents,
        autopilot=True,
        autopilot_stage="research",
    )
    db.add(project)
    db.flush()
    db.add(
        Brief(
            project_id=project.id,
            topic=topic.strip()[:500],
            audience=(audience or config.audience)[:500],
            objective="Explicar com precisão e maximizar a retenção",
            language=language,
            constraints={"duration_seconds": duration_seconds or config.duration_seconds, "tone": "envolvente e didático", "angle": angle},
        )
    )
    if suggestion is not None:
        suggestion.status, suggestion.project_id = "used", project.id
    audit(db, project.id, "autopilot.started", project, actor, topic=topic, suggestion=suggestion.id if suggestion else None)
    return project


def continue_project(db: Session, project_id: int, storage: Storage) -> None:
    """Queue the next stage; without a queue (tests, local scripts) run stages inline until blocked or done."""
    db.commit()
    if enqueue({"type": "autopilot", "project_id": project_id}):
        return
    drive(db, project_id, storage)


def drive(db: Session, project_id: int, storage: Storage, max_steps: int = 20) -> str:
    stage = ""
    for _ in range(max_steps):
        stage = advance(db, project_id, storage)
        if stage in TERMINAL or stage == WAITING:
            break
    return stage


def on_job(db: Session, project_id: int, storage: Storage) -> None:
    stage = advance(db, project_id, storage)
    if stage not in TERMINAL and stage != WAITING:
        enqueue({"type": "autopilot", "project_id": project_id})


def _latest(db: Session, model, project_id: int):
    return db.scalar(select(model).where(model.project_id == project_id).order_by(model.id.desc()))


def _block(db: Session, project: Project, stage: str, reason: str) -> str:
    project.autopilot_stage = "needs_review"
    project.autopilot_reason = f"[{stage}] {reason}"[:4000]
    set_status(db, project, ProjectStatus.REVIEW, ACTOR, "piloto automático aguarda revisão humana")
    audit(db, project.id, "autopilot.blocked", project, ACTOR, stage=stage, reason=reason[:500])
    db.commit()
    return "needs_review"


def advance(db: Session, project_id: int, storage: Storage) -> str:
    """Runs exactly one stage, records it as a StageRun and returns the new stage."""
    project = db.get(Project, project_id)
    if project is None or not project.autopilot:
        return "stopped"
    stage = project.autopilot_stage or "research"
    if stage in TERMINAL:
        return stage
    run = StageRun(project_id=project.id, stage=stage, started_at=utcnow())
    db.add(run)
    db.flush()
    started, spent_before = time.monotonic(), project.spent_cents
    handler = HANDLERS[stage]
    try:
        next_stage, score, detail = handler(db, project, storage)
        run.status = "waiting" if next_stage == WAITING else "completed"
    except Blocked as exc:
        # Keep what the stage already recorded (review, cost); only the advance is withheld.
        run.status, run.finished_at = "blocked", utcnow()
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.cost_cents = max(0, project.spent_cents - spent_before)
        run.detail = {"reason": str(exc)}
        return _block(db, project, stage, str(exc))
    except Exception as exc:  # noqa: BLE001 - any stage failure is surfaced in the exception inbox
        logger.exception("Autopilot stage %s failed for project %s", stage, project_id)
        db.rollback()
        project = db.get(Project, project_id)
        db.add(StageRun(project_id=project.id, stage=stage, status="failed", started_at=utcnow(), detail={"error": str(exc)[:1000]}))
        return _block(db, project, stage, f"Falha técnica: {exc}")
    run.finished_at = utcnow()
    run.duration_ms = int((time.monotonic() - started) * 1000)
    run.cost_cents = max(0, project.spent_cents - spent_before)
    run.score, run.detail = score, detail
    if next_stage != WAITING:
        project.autopilot_stage = next_stage
        if next_stage == "done":
            project.autopilot_reason = None
    db.commit()
    return next_stage


def _research(db: Session, project: Project, storage: Storage):
    from .routers.generation import research_project

    dossier = research_project(db, project, ACTOR)
    return "script", None, {"dossier_id": dossier.id, "facts": len(dossier.facts), "provider": dossier.provider}


def _script(db: Session, project: Project, storage: Storage, feedback: str = ""):
    from .routers.generation import script_project

    script = script_project(db, project, ACTOR, feedback=feedback)
    return "script_gate", None, {"script_id": script.id, "version": script.version, "author": script.author}


def _approve(db: Session, project: Project, gate: str, target_id: int, note: str) -> None:
    approval = db.scalar(
        select(Approval).where(Approval.project_id == project.id, Approval.gate == gate, Approval.target_id == target_id)
    )
    if approval:
        approval.approved, approval.actor, approval.note = True, ACTOR, note
    else:
        approval = Approval(project_id=project.id, gate=gate, target_id=target_id, approved=True, actor=ACTOR, note=note)
        db.add(approval)
    db.flush()
    audit(db, project.id, "approval.set", approval, ACTOR, gate=gate, approved=True)
    set_status(db, project, ProjectStatus.APPROVED, ACTOR, f"aprovação automática: {gate}")


def _gate_note(result: GateResult) -> str:
    issues = "; ".join(result.issues[:5])
    return f"Nota {result.score:.0f}." + (f" Observações: {issues}" if issues else "")


def _script_gate(db: Session, project: Project, storage: Storage):
    config = settings_for(db, project.organization_id)
    script = _latest(db, ScriptVersion, project.id)
    brief = _latest(db, Brief, project.id)
    duration = int((brief.constraints or {}).get("duration_seconds", config.duration_seconds))
    result = review_script(
        get_ai(), script, _latest(db, ResearchDossier, project.id), duration, config.script_threshold, list(config.banned_topics or [])
    )
    project.spent_cents += result.cost_cents
    script.metadata_json = {**(script.metadata_json or {}), "review": {"score": result.score, "issues": result.issues, **result.detail}}
    audit(db, project.id, "script.reviewed", script, ACTOR, cost_cents=result.cost_cents, score=result.score, passed=result.passed)
    detail = {"script_id": script.id, "issues": result.issues, **result.detail}
    if result.passed:
        _approve(db, project, "script", script.id, _gate_note(result))
        return "media", result.score, detail
    rewrites = db.scalar(
        select(func.count()).where(StageRun.project_id == project.id, StageRun.stage == "script_gate", StageRun.status == "completed")
    ) or 0
    safety = result.detail.get("safety_ok", True) and not any(issue.startswith("Tema proibido") for issue in result.issues)
    if safety and rewrites < MAX_REWRITES:
        _script(db, project, storage, feedback="\n".join(f"- {issue}" for issue in result.issues))
        return "script_gate", result.score, {**detail, "rewritten": True}
    raise Blocked(f"Roteiro v{script.version} com nota {result.score:.0f} (mínimo {config.script_threshold}): " + "; ".join(result.issues[:5]))


def _media(db: Session, project: Project, storage: Storage):
    from .production import produce_media

    script = _latest(db, ScriptVersion, project.id)
    summary, _ = produce_media(db, project, script, storage, ACTOR)
    return "render", None, summary.__dict__


def _render(db: Session, project: Project, storage: Storage):
    from .routers.generation import ensure_storyboard

    script = _latest(db, ScriptVersion, project.id)
    render = db.scalar(
        select(Render).where(Render.project_id == project.id, Render.script_version_id == script.id).order_by(Render.id.desc())
    )
    if render is None or render.status == "superseded":
        scenes = ensure_storyboard(db, script)
        render = Render(project_id=project.id, script_version_id=script.id, status="queued", idempotency_key=f"autopilot-{project.id}-{script.id}-{uuid.uuid4().hex[:8]}")
        db.add(render)
        db.flush()
        audit(db, project.id, "render.queued", render, ACTOR, scenes=len(scenes), engine="kokoro+ffmpeg")
        set_status(db, project, ProjectStatus.PROCESSING, ACTOR, "renderização automática")
        db.commit()
        if enqueue({"render_id": render.id, "attempt": 1}):
            return WAITING, None, {"render_id": render.id}
        from pipeline.service import execute_render, mark_failed

        try:
            execute_render(db, render.id, storage)
        except Exception as exc:  # noqa: BLE001 - surfaced by the render gate
            mark_failed(db, render.id, str(exc))
        db.refresh(render)
    if render.status in {"queued", "processing"}:
        return WAITING, None, {"render_id": render.id}
    return "render_gate", None, {"render_id": render.id, "status": render.status}


def _render_gate(db: Session, project: Project, storage: Storage):
    render = _latest(db, Render, project.id)
    result = review_render(db, render, storage, get_settings())
    detail = {"render_id": render.id, "issues": result.issues, **result.detail}
    if not result.passed:
        raise Blocked("Render reprovado: " + "; ".join(result.issues[:5]))
    _approve(db, project, "publish", render.id, _gate_note(result))
    return "publish", result.score, detail


def _connection(db: Session, project: Project, platform: str) -> ChannelConnection:
    existing = db.scalar(
        select(ChannelConnection).where(
            ChannelConnection.project_id == project.id, ChannelConnection.platform == platform, ChannelConnection.enabled.is_(True)
        )
    )
    if existing:
        return existing
    account = active_account(db, project.organization_id, platform) if platform != "local" else None
    connection = ChannelConnection(
        project_id=project.id,
        platform=platform if (account or platform == "local") else "local",
        external_account_id=account.external_account_id if account else "narra-autopilot",
        account_id=account.id if account else None,
    )
    db.add(connection)
    db.flush()
    return connection


def next_slot(db: Session, organization_id: int, cadence_hours: int):
    last = db.scalar(
        select(func.max(func.coalesce(Publication.scheduled_at, Publication.published_at)))
        .join(Project, Project.id == Publication.project_id)
        .where(Project.organization_id == organization_id, Publication.status.in_(["scheduled", "published", "processing"]))
    )
    if last is None:
        return None
    slot = last + timedelta(hours=cadence_hours)
    return slot if slot > utcnow() else None


def _publish(db: Session, project: Project, storage: Storage):
    config = settings_for(db, project.organization_id)
    settings = get_settings()
    if not config.auto_publish:
        raise Blocked("Publicação automática desativada: revise e publique manualmente")
    render = _latest(db, Render, project.id)
    script = db.get(ScriptVersion, render.script_version_id)
    meta = script.metadata_json or {}
    connection = _connection(db, project, config.platform)
    live = bool(
        config.live_publish
        and is_authorized(connection)
        and live_allowed(db, project.organization_id, connection.platform, settings)
    )
    variants = [title for title in meta.get("title_variants") or [] if title] or [meta.get("title") or project.name]
    title = variants[0][:300]
    if len(variants) > 1:
        # One video can only carry one title, so variants alternate across videos and the playbook compares styles.
        running = db.scalar(
            select(func.count()).select_from(Experiment).join(Project, Project.id == Experiment.project_id)
            .where(Project.organization_id == project.organization_id, Experiment.name.like("Título:%"))
        ) or 0
        published = "A" if running % 2 == 0 else "B"
        title = variants[0 if published == "A" else 1][:300]
        db.add(
            Experiment(
                project_id=project.id,
                name=f"Título: {project.name}"[:300],
                hypothesis="Estilos de título (pergunta, número, tamanho) mudam as visualizações nas primeiras 48h.",
                variants={"A": variants[0], "B": variants[1], "metric": "views", "published": published, "origin": ACTOR},
                status="running",
            )
        )
    scheduled = next_slot(db, project.organization_id, config.cadence_hours)
    publication = Publication(
        project_id=project.id,
        render_id=render.id,
        connection_id=connection.id,
        title=title,
        description=with_credits(str(meta.get("description") or ""), credits_for(db, script.id)),
        live=live,
        status="scheduled" if scheduled else "publishing",
        idempotency_key=f"autopilot-pub-{render.id}",
        scheduled_at=scheduled,
    )
    db.add(publication)
    db.flush()
    audit(db, project.id, "publication.requested", publication, ACTOR, live=live, scheduled=bool(scheduled))
    db.commit()
    if publication.status == "publishing":
        execute_publication(db, publication, storage, settings, ACTOR)
    return "done", None, {"publication_id": publication.id, "live": live, "scheduled_at": scheduled.isoformat() if scheduled else None}


HANDLERS = {
    "research": _research,
    "script": _script,
    "script_gate": _script_gate,
    "media": _media,
    "render": _render,
    "render_gate": _render_gate,
    "publish": _publish,
}


def resume(db: Session, project: Project, actor: str, approve: bool, storage: Storage) -> Project:
    """Human decision on a blocked project: approve the gate it stopped at, or retry the stage."""
    blocked = db.scalar(
        select(StageRun).where(StageRun.project_id == project.id, StageRun.status.in_(["blocked", "failed"])).order_by(StageRun.id.desc())
    )
    stage = blocked.stage if blocked else "research"
    if approve and stage == "script_gate":
        script = _latest(db, ScriptVersion, project.id)
        _human_approve(db, project, "script", script.id, actor)
        stage = "media"
    elif stage in {"render", "render_gate"} and (render := _latest(db, Render, project.id)) and render.status == "failed":
        render.status, stage = "superseded", "render"
    elif approve and stage == "render_gate":
        _human_approve(db, project, "publish", _latest(db, Render, project.id).id, actor)
        stage = "publish"
    project.autopilot, project.autopilot_stage, project.autopilot_reason = True, stage, None
    audit(db, project.id, "autopilot.resumed", project, actor, stage=stage, approved=approve)
    continue_project(db, project.id, storage)
    return project


def _human_approve(db: Session, project: Project, gate: str, target_id: int, actor: str) -> None:
    approval = db.scalar(select(Approval).where(Approval.project_id == project.id, Approval.gate == gate, Approval.target_id == target_id))
    if approval:
        approval.approved, approval.actor, approval.note = True, actor, "aprovado na caixa de exceções"
    else:
        db.add(Approval(project_id=project.id, gate=gate, target_id=target_id, approved=True, actor=actor, note="aprovado na caixa de exceções"))
    audit(db, project.id, "approval.set", project, actor, gate=gate, approved=True, override=True)


def stage_for_existing(db: Session, project: Project) -> str:
    script = _latest(db, ScriptVersion, project.id)
    if not _latest(db, ResearchDossier, project.id):
        return "research"
    if not script:
        return "script"
    approved_script = db.scalar(
        select(Approval).where(Approval.project_id == project.id, Approval.gate == "script", Approval.target_id == script.id, Approval.approved.is_(True))
    )
    if not approved_script:
        return "script_gate"
    render = db.scalar(select(Render).where(Render.project_id == project.id, Render.script_version_id == script.id).order_by(Render.id.desc()))
    if not render or render.status == "failed":
        return "media"
    if render.status != "completed":
        return "render"
    if db.scalar(select(Publication).where(Publication.render_id == render.id)):
        return "done"
    return "render_gate"


def in_flight(db: Session, organization_id: int) -> int:
    return db.scalar(
        select(func.count()).where(
            Project.organization_id == organization_id,
            Project.autopilot.is_(True),
            Project.autopilot_stage.not_in(list(TERMINAL)),
        )
    ) or 0


def tick(db: Session, storage: Storage) -> list[int]:
    """Scheduler: each enabled organization starts one new video per cadence window, picking the best topic."""
    from .learning import plan_topics

    started: list[int] = []
    for config in db.scalars(select(AutopilotSettings).where(AutopilotSettings.enabled.is_(True))):
        if in_flight(db, config.organization_id):
            continue
        last = db.scalar(
            select(func.max(Project.created_at)).where(Project.organization_id == config.organization_id, Project.autopilot.is_(True))
        )
        if last and utcnow() - last < timedelta(hours=config.cadence_hours):
            continue
        organization = db.get(Organization, config.organization_id)
        suggestion = _next_topic(db, config.organization_id)
        if suggestion is None:
            plan_topics(db, organization, ACTOR)
            suggestion = _next_topic(db, config.organization_id)
        if suggestion is None:
            continue
        project = create_project(db, organization, "scheduler", suggestion.topic, angle=suggestion.angle, suggestion=suggestion)
        db.commit()
        continue_project(db, project.id, storage)
        started.append(project.id)
    return started


def _next_topic(db: Session, organization_id: int) -> TopicSuggestion | None:
    return db.scalar(
        select(TopicSuggestion)
        .where(TopicSuggestion.organization_id == organization_id, TopicSuggestion.status == "proposed")
        .order_by(TopicSuggestion.predicted_score.desc(), TopicSuggestion.id)
    )
