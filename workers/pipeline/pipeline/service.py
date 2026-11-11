import json
import logging
import random
import tempfile
import time
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import KOKORO_VOICES, voice_for
from app.config import get_settings
from app.database import engine
from app.deps import audit, set_status
from app.models import Asset, Organization, Project, Render, Scene, ScriptVersion, utcnow
from app.autopilot import tick as autopilot_tick
from app.learning import learning_tick
from app.publishing import run_due_publications
from app.retention import shots_for
from app.storage import Storage, build_storage
from video_ai_contracts import ProjectStatus, RenderRequest, SceneSpec, ShotSpec

from .tts import load_voice
from .worker import render_video

logger = logging.getLogger("narra.worker")
RENDER_QUEUE = "video-ai:render-jobs"
DEAD_LETTER = "video-ai:render-dead-letter"
CONTENT_TYPES = {"video": "video/mp4", "manifest": "application/json"}
# Longer than any legitimate render, so a job owned by another live worker is never stolen.
STALE_RENDER_AFTER = timedelta(minutes=30)
AUTOPILOT_TICK_SECONDS = 300


def estimated_timeline(specs: list[SceneSpec]) -> list[dict]:
    """Planned timeline for manifest renders (no FFmpeg), so retention analysis still has shot boundaries."""
    timeline, cursor = [], 0.0
    for spec in specs:
        shots = spec.shots or [ShotSpec(duration=spec.duration_seconds, media_kind=spec.media_kind, role="scene")]
        for position, shot in enumerate(shots, 1):
            timeline.append(
                {"scene": spec.position, "shot": position, "start": round(cursor, 2), "end": round(cursor + shot.duration, 2),
                 "asset_id": shot.asset_id, "kind": shot.media_kind or "generated", "role": shot.role, "effect": shot.effect}
            )
            cursor += shot.duration
    return timeline


def execute_render(db: Session, render_id: int, storage: Storage) -> Render | None:
    render = db.get(Render, render_id)
    if not render or render.status in {"completed", "cancelled"}:
        return render
    project = db.get(Project, render.project_id)
    organization = db.get(Organization, project.organization_id)
    script = db.get(ScriptVersion, render.script_version_id)
    render.status, render.started_at, render.error = "processing", utcnow(), None
    render.attempts += 1
    render.progress = 2
    db.commit()

    scenes = list(db.scalars(select(Scene).where(Scene.script_version_id == script.id).order_by(Scene.position)))

    def report(progress: int) -> None:
        render.progress = progress
        db.commit()

    with ExitStack() as stack, tempfile.TemporaryDirectory() as tmp:
        local: dict[int, tuple[str, str]] = {}

        def media(asset_id: int | None) -> tuple[str | None, str | None]:
            if not asset_id:
                return None, None
            if asset_id not in local:
                asset = db.get(Asset, asset_id)
                if not asset or asset.status != "ready":
                    return None, None
                local[asset_id] = (str(stack.enter_context(storage.local_copy(asset.uri))), asset.kind)
            return local[asset_id]

        planned = shots_for(db, [scene.id for scene in scenes])
        specs = []
        for scene in scenes:
            media_path, media_kind = media(scene.media_asset_id)
            shots = []
            for shot in planned.get(scene.id, []):
                shot_path, shot_kind = media(shot.asset_id)
                shots.append(
                    ShotSpec(
                        duration=shot.duration,
                        media_path=shot_path,
                        media_kind=shot_kind,
                        effect=shot.effect,
                        clip_start=shot.clip_start,
                        role=shot.role,
                        asset_id=shot.asset_id,
                    )
                )
            specs.append(
                SceneSpec(
                    position=scene.position,
                    narration=scene.narration,
                    duration_seconds=scene.duration_seconds,
                    media_path=media_path,
                    media_kind=media_kind,
                    shots=shots,
                )
            )
        artifact = render_video(
            RenderRequest(
                render_id=render.id,
                script=script.content,
                output_dir=tmp,
                scenes=specs,
                voice=voice_for(organization, project.language or "pt-BR"),
            ),
            report,
        )
        output = Path(artifact.uri)
        content_type = CONTENT_TYPES.get(artifact.kind, "application/octet-stream")
        key = f"orgs/{organization.id}/projects/{project.id}/renders/render-{render.id}{'.mp4' if artifact.kind == 'video' else '.json'}"
        size = output.stat().st_size
        storage.put_file(output, key, content_type)

    render.status, render.progress, render.finished_at = "completed", 100, utcnow()
    render.artifact_uri, render.artifact_kind = key, artifact.kind
    render.timeline = artifact.metadata.get("timeline") or estimated_timeline(specs)
    project.spent_cents += render.cost_cents
    db.add(
        Asset(
            project_id=project.id,
            kind="render",
            uri=key,
            filename=Path(key).name,
            content_type=content_type,
            size_bytes=size,
            status="ready",
            metadata_json={**artifact.metadata, "render_id": render.id},
        )
    )
    audit(
        db,
        project.id,
        "render.completed",
        render,
        "worker",
        cost_cents=render.cost_cents,
        artifact_kind=artifact.kind,
        tts=artifact.metadata.get("tts"),
    )
    set_status(db, project, ProjectStatus.REVIEW, "worker", "prévia pronta para aprovação")
    db.commit()
    return render


def mark_failed(db: Session, render_id: int, error: str) -> None:
    db.rollback()
    render = db.get(Render, render_id)
    if not render:
        return
    render.status, render.error, render.finished_at = "failed", error[:4000], utcnow()
    project = db.get(Project, render.project_id)
    audit(db, render.project_id, "render.failed", render, "worker", error=error[:500])
    set_status(db, project, ProjectStatus.FAILED, "worker", "falha na renderização")
    db.commit()


def note_retry(db: Session, render_id: int, attempt: int, error: str) -> None:
    db.rollback()
    render = db.get(Render, render_id)
    if render:
        render.status, render.error = "queued", f"Tentativa {attempt} falhou: {error[:500]}"
        db.commit()


def handle_job(queue: Redis, raw: bytes, storage: Storage, max_attempts: int) -> None:
    payload = json.loads(raw)
    kind = payload.get("type", "render")
    if kind != "render":
        handle_task(queue, payload, storage)
        return
    render_id, attempt = int(payload["render_id"]), int(payload.get("attempt", 1))
    with Session(engine) as db:
        try:
            execute_render(db, render_id, storage)
        except Exception as exc:  # noqa: BLE001 - every failure is retried or dead-lettered
            logger.exception("Render %s failed on attempt %s", render_id, attempt)
            if attempt < max_attempts:
                note_retry(db, render_id, attempt, str(exc))
                time.sleep(min(30, 2**attempt) + random.random())
                queue.rpush(RENDER_QUEUE, json.dumps({"render_id": render_id, "attempt": attempt + 1}))
            else:
                mark_failed(db, render_id, str(exc))
                queue.rpush(DEAD_LETTER, json.dumps({"payload": payload, "error": str(exc)}))
                after_render(db, render_id, storage)
            return
        after_render(db, render_id, storage)


def after_render(db: Session, render_id: int, storage: Storage) -> None:
    """Autopilot projects continue (render gate) as soon as their render finishes or fails."""
    render = db.get(Render, render_id)
    project = db.get(Project, render.project_id) if render else None
    if project and project.autopilot and project.autopilot_stage == "render":
        from app.autopilot import continue_project

        continue_project(db, project.id, storage)


def handle_task(queue: Redis, payload: dict, storage: Storage) -> None:
    kind = payload["type"]
    with Session(engine) as db:
        try:
            if kind == "research":
                from app.routers.generation import research_project

                project = db.get(Project, int(payload["project_id"]))
                research_project(db, project, payload.get("actor", "worker"))
                db.commit()
            elif kind == "media":
                from app.production import produce_media

                project = db.get(Project, int(payload["project_id"]))
                script = db.get(ScriptVersion, int(payload["script_version_id"]))
                produce_media(db, project, script, storage, payload.get("actor", "worker"))
                db.commit()
            elif kind == "autopilot":
                from app.autopilot import on_job

                on_job(db, int(payload["project_id"]), storage)
            else:
                logger.warning("Unknown job type %s", kind)
        except Exception as exc:  # noqa: BLE001 - tasks report failure on the project, never crash the worker
            logger.exception("Task %s failed", kind)
            db.rollback()
            queue.rpush(DEAD_LETTER, json.dumps({"payload": payload, "error": str(exc)}))
            if kind == "research":
                project = db.get(Project, int(payload["project_id"]))
                audit(db, project.id, "research.failed", project, "worker", error=str(exc)[:500])
                db.commit()


def recover_stale_renders(queue: Redis, max_attempts: int) -> None:
    cutoff = utcnow() - STALE_RENDER_AFTER
    with Session(engine) as db:
        stale = list(db.scalars(select(Render).where(Render.status == "processing", Render.started_at < cutoff)))
        for render in stale:
            reason = "worker interrompido durante a renderização"
            if render.attempts < max_attempts:
                note_retry(db, render.id, render.attempts, reason)
                queue.rpush(RENDER_QUEUE, json.dumps({"render_id": render.id, "attempt": render.attempts + 1}))
                logger.warning("Render %s was stale; requeued", render.id)
            else:
                mark_failed(db, render.id, reason)
                queue.rpush(DEAD_LETTER, json.dumps({"payload": {"render_id": render.id}, "error": reason}))
                logger.warning("Render %s was stale; dead-lettered", render.id)


def ensure_voice_samples(storage: Storage) -> None:
    voice = load_voice()
    if not voice:
        return
    for item in KOKORO_VOICES:
        key = f"voices/{item['id']}.wav"
        if storage.head(key) is not None:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample.wav"
            phrase = (
                f"Hi! I'm {item['label']}, and I'll narrate your explainer videos on Narra."
                if item["language"].startswith("en")
                else f"Olá! Eu sou a voz {item['label']}. Vou narrar seus vídeos explicativos no Narra."
            )
            voice.synthesize(phrase, target, item["id"])
            storage.put_file(target, key, "audio/wav")
        logger.info("Voice sample generated for %s", item["id"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    storage = build_storage(settings)
    for _ in range(10):
        try:
            storage.ensure_bucket()
            break
        except Exception as exc:  # noqa: BLE001 - storage may still be starting
            logger.warning("Storage not ready: %s", exc)
            time.sleep(3)
    try:
        ensure_voice_samples(storage)
    except Exception:  # noqa: BLE001 - samples are optional
        logger.exception("Voice sample generation failed")
    queue = Redis.from_url(settings.redis_url, socket_connect_timeout=5, socket_timeout=15, health_check_interval=30)
    logger.info("Worker started")
    last_recovery = last_autopilot = 0.0
    learning_runs: dict = {}
    while True:
        if time.monotonic() - last_recovery > 60:
            last_recovery = time.monotonic()
            try:
                recover_stale_renders(queue, settings.render_max_attempts)
            except Exception:  # noqa: BLE001 - recovery must not stop the worker
                logger.exception("Stale render recovery failed")
        if time.monotonic() - last_autopilot > AUTOPILOT_TICK_SECONDS:
            last_autopilot = time.monotonic()
            try:
                with Session(engine) as db:
                    started = autopilot_tick(db, storage)
                    if started:
                        logger.info("Autopilot started projects %s", started)
                    learning_tick(db, learning_runs)
            except Exception:  # noqa: BLE001 - the scheduler must not stop the worker
                logger.exception("Autopilot tick failed")
        item = queue.blpop(RENDER_QUEUE, timeout=5)
        if item:
            handle_job(queue, item[1], storage, settings.render_max_attempts)
        try:
            with Session(engine) as db:
                run_due_publications(db, storage, settings)
        except Exception:  # noqa: BLE001 - scheduler must not stop the worker
            logger.exception("Scheduled publication check failed")


if __name__ == "__main__":
    main()
