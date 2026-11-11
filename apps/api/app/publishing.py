from sqlalchemy import select
from sqlalchemy.orm import Session

from video_ai_contracts import ProjectStatus, PublishRequest

from .adapters import publisher_for
from .config import Settings
from .deps import audit, set_status
from .models import ChannelConnection, Project, Publication, Render, utcnow
from .oauth import OAuthService
from .storage import Storage


def access_token_for(connection: ChannelConnection, oauth: OAuthService) -> str | None:
    encrypted = (connection.config or {}).get("access_token_encrypted")
    return oauth.decrypt(encrypted) if encrypted else None


def execute_publication(
    db: Session,
    publication: Publication,
    storage: Storage,
    settings: Settings,
    actor: str = "system",
) -> Publication:
    """Runs the platform publisher; raises on failure after recording the error."""
    render = db.get(Render, publication.render_id)
    connection = db.get(ChannelConnection, publication.connection_id)
    project = db.get(Project, publication.project_id)
    try:
        adapter = publisher_for(
            connection.platform,
            publication.live,
            settings,
            access_token_for(connection, OAuthService(settings)),
        )
        request = PublishRequest(
            title=publication.title,
            description=publication.description,
            artifact_uri=render.artifact_uri or "",
            idempotency_key=publication.idempotency_key,
        )
        if publication.live:
            with storage.local_copy(render.artifact_uri) as path:
                result = adapter.publish(request.model_copy(update={"artifact_uri": str(path)}))
        else:
            result = adapter.publish(request)
    except Exception as exc:
        publication.status, publication.error = "failed", str(exc)
        audit(db, project.id, "publication.failed", publication, actor, error=str(exc))
        db.commit()
        raise
    publication.external_id, publication.url, publication.simulated = result.external_id, result.url, result.simulated
    publication.error = None
    if publication.live:
        publication.status = "processing"
        set_status(db, project, ProjectStatus.PUBLISHING, actor, "publicação enviada à plataforma")
    else:
        publication.status, publication.published_at = "published", utcnow()
        set_status(db, project, ProjectStatus.PUBLISHED, actor, "publicação simulada concluída")
    audit(db, project.id, "publication.completed", publication, actor, live=publication.live)
    db.commit()
    return publication


def run_due_publications(db: Session, storage: Storage, settings: Settings) -> int:
    due = list(
        db.scalars(
            select(Publication).where(Publication.status == "scheduled", Publication.scheduled_at <= utcnow())
        )
    )
    for publication in due:
        try:
            execute_publication(db, publication, storage, settings, "scheduler")
        except Exception:  # noqa: BLE001 - recorded on the publication row
            continue
    return len(due)
