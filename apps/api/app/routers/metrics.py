import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..adapters import metrics_for
from ..auth import CurrentContext, EditorContext
from ..channels import access_token_for
from ..config import get_settings
from ..deps import DbSession, audit, require_project
from ..models import ChannelConnection, Experiment, Insight, MetricSnapshot, Publication
from ..schemas import (
    ExperimentCreate,
    ExperimentOut,
    InsightOut,
    MetricCreate,
    MetricOut,
    ProjectMetrics,
)
from .publications import require_publication

router = APIRouter(tags=["metrics"])


@router.post("/publications/{publication_id}/metrics", response_model=MetricOut, status_code=201)
def add_metrics(publication_id: int, body: MetricCreate, ctx: EditorContext, db: DbSession):
    publication = require_publication(db, ctx, publication_id)
    snapshot = db.scalar(
        select(MetricSnapshot).where(
            MetricSnapshot.publication_id == publication_id,
            MetricSnapshot.window_hours == body.window_hours,
        )
    )
    if snapshot:
        for key, value in body.model_dump().items():
            setattr(snapshot, key, value)
    else:
        snapshot = MetricSnapshot(publication_id=publication_id, **body.model_dump())
        db.add(snapshot)
    db.flush()
    audit(db, publication.project_id, "metrics.captured", snapshot, ctx.actor)
    db.commit()
    return snapshot


@router.post("/publications/{publication_id}/metrics/refresh", response_model=MetricOut, status_code=201)
def refresh_metrics(publication_id: int, ctx: EditorContext, db: DbSession, window_hours: int = 24):
    publication = require_publication(db, ctx, publication_id)
    if publication.simulated or not publication.external_id:
        raise HTTPException(409, "É necessária uma publicação real")
    connection = db.get(ChannelConnection, publication.connection_id)
    token = access_token_for(db, connection, get_settings())
    if not token:
        raise HTTPException(409, "Credenciais OAuth são necessárias")
    try:
        values = metrics_for(connection.platform, token).fetch(publication.external_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Falha ao coletar métricas: {exc}")
    return add_metrics(publication_id, MetricCreate(**values, window_hours=window_hours), ctx, db)


@router.get("/publications/{publication_id}/metrics", response_model=list[MetricOut])
def list_metrics(publication_id: int, ctx: CurrentContext, db: DbSession):
    require_publication(db, ctx, publication_id)
    return list(
        db.scalars(
            select(MetricSnapshot)
            .where(MetricSnapshot.publication_id == publication_id)
            .order_by(MetricSnapshot.window_hours)
        )
    )


def compute_metrics(db: DbSession, project_id: int) -> ProjectMetrics:
    snapshots = db.scalars(
        select(MetricSnapshot)
        .join(Publication, MetricSnapshot.publication_id == Publication.id)
        .where(Publication.project_id == project_id)
        .order_by(MetricSnapshot.captured_at.desc())
    )
    latest: dict[int, MetricSnapshot] = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.publication_id, snapshot)
    totals = {
        "views": sum(item.views for item in latest.values()),
        "likes": sum(item.likes for item in latest.values()),
        "comments": sum(item.comments for item in latest.values()),
        "shares": sum(item.shares for item in latest.values()),
    }
    interactions = totals["likes"] + totals["comments"] + totals["shares"]
    return ProjectMetrics(
        **totals,
        engagement_rate=round(interactions / totals["views"], 4) if totals["views"] else 0,
        publications_measured=len(latest),
    )


@router.get("/projects/{project_id}/metrics", response_model=ProjectMetrics)
def project_metrics(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return compute_metrics(db, project_id)


@router.post("/projects/{project_id}/insights", response_model=InsightOut, status_code=201)
def generate_insight(project_id: int, ctx: EditorContext, db: DbSession):
    require_project(db, ctx, project_id)
    totals = compute_metrics(db, project_id)
    if not totals.views:
        text = "Ainda sem visualizações medidas: registre métricas após publicar para receber recomendações."
    elif totals.engagement_rate < 0.05:
        text = "Engajamento abaixo de 5% das visualizações: teste um CTA mais direto e uma pergunta nos 3 primeiros segundos."
    else:
        text = "Bom engajamento: mantenha o formato e teste uma nova abertura para ampliar o alcance."
    insight = Insight(project_id=project_id, text=text, evidence=totals.model_dump())
    db.add(insight)
    db.flush()
    audit(db, project_id, "insight.generated", insight, ctx.actor)
    db.commit()
    return insight


@router.get("/projects/{project_id}/insights", response_model=list[InsightOut])
def list_insights(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(db.scalars(select(Insight).where(Insight.project_id == project_id).order_by(Insight.id.desc())))


@router.post("/projects/{project_id}/experiments", response_model=ExperimentOut, status_code=201)
def create_experiment(project_id: int, body: ExperimentCreate, ctx: EditorContext, db: DbSession):
    require_project(db, ctx, project_id)
    experiment = Experiment(project_id=project_id, **body.model_dump())
    db.add(experiment)
    db.flush()
    audit(db, project_id, "experiment.created", experiment, ctx.actor)
    db.commit()
    return experiment


@router.get("/projects/{project_id}/experiments", response_model=list[ExperimentOut])
def list_experiments(project_id: int, ctx: CurrentContext, db: DbSession):
    require_project(db, ctx, project_id)
    return list(db.scalars(select(Experiment).where(Experiment.project_id == project_id).order_by(Experiment.id.desc())))
