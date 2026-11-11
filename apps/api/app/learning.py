import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import timedelta
from statistics import mean
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai import get_ai, safe_complete
from .config import get_settings
from .deps import audit
from .models import (
    Brief,
    ChannelConnection,
    Experiment,
    MetricSnapshot,
    Organization,
    PlaybookRule,
    Project,
    Publication,
    Render,
    RetentionCurve,
    ScriptVersion,
    TopicSuggestion,
    utcnow,
)
from .textutil import LANGUAGE_NAME, similar

logger = logging.getLogger("narra.learning")
DEFAULT_PARAMS: dict[str, Any] = {"shot_seconds": 3.0, "hook_media": "best", "reveal_ratio": 0.6}
MIN_SAMPLES = 2


@dataclass
class PlaybookContext:
    text: str = ""
    params: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    rules: list[PlaybookRule] = field(default_factory=list)


def active_rules(db: Session, organization_id: int) -> list[PlaybookRule]:
    return list(
        db.scalars(
            select(PlaybookRule)
            .where(PlaybookRule.organization_id == organization_id, PlaybookRule.active.is_(True))
            .order_by(PlaybookRule.confidence.desc(), PlaybookRule.id.desc())
        )
    )


def playbook_context(db: Session, organization_id: int) -> PlaybookContext:
    """Rules learned from real metrics, as prompt text plus numeric knobs for the planners."""
    rules = active_rules(db, organization_id)
    params = dict(DEFAULT_PARAMS)
    for rule in reversed(rules):
        params.update({key: value for key, value in (rule.value or {}).items() if key in DEFAULT_PARAMS or key.startswith("prefer_")})
    text = "\n".join(f"- {rule.text} (confiança {rule.confidence:.0%})" for rule in rules[:12])
    return PlaybookContext(text=text, params=params, rules=rules)


# --- Metrics and retention ---------------------------------------------------------------------------------------


def analyze_drops(points: list[list[float]], timeline: list[dict], duration: float, limit: int = 3) -> list[dict]:
    """Largest audience losses between consecutive curve points, mapped to the shot on screen at that moment."""
    ordered = sorted((float(ratio), float(watch)) for ratio, watch in points)
    losses = []
    for (r0, w0), (r1, w1) in zip(ordered, ordered[1:]):
        if w1 < w0:
            losses.append((w0 - w1, r0, r1))
    drops = []
    for loss, r0, r1 in sorted(losses, reverse=True)[:limit]:
        at = (r0 + r1) / 2 * duration
        shot = next((item for item in timeline if item.get("start", 0) <= at < item.get("end", 0)), None) or {}
        drops.append(
            {
                "at": round(at, 1),
                "ratio": round((r0 + r1) / 2, 3),
                "loss": round(loss, 3),
                "scene": shot.get("scene"),
                "shot": shot.get("shot"),
                "role": shot.get("role"),
                "kind": shot.get("kind"),
                "asset_id": shot.get("asset_id"),
            }
        )
    return sorted(drops, key=lambda drop: drop["at"])


def render_duration(render: Render) -> float:
    return max((float(item.get("end", 0)) for item in render.timeline or []), default=0.0)


def store_retention(db: Session, publication: Publication, points: list[list[float]]) -> RetentionCurve:
    render = db.get(Render, publication.render_id)
    drops = analyze_drops(points, render.timeline or [], render_duration(render) or 60) if render else []
    curve = db.scalar(select(RetentionCurve).where(RetentionCurve.publication_id == publication.id))
    if curve is None:
        curve = RetentionCurve(publication_id=publication.id)
        db.add(curve)
    curve.points, curve.drops, curve.captured_at = [[float(r), float(w)] for r, w in points], drops, utcnow()
    db.flush()
    return curve


def youtube_retention(token: str, video_id: str, published_at) -> list[list[float]]:
    start = (published_at or utcnow() - timedelta(days=30)).date().isoformat()
    response = httpx.get(
        "https://youtubeanalytics.googleapis.com/v2/reports",
        params={
            "ids": "channel==MINE",
            "startDate": start,
            "endDate": utcnow().date().isoformat(),
            "metrics": "audienceWatchRatio",
            "dimensions": "elapsedVideoTimeRatio",
            "filters": f"video=={video_id}",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    return [[float(row[0]), float(row[1])] for row in response.json().get("rows") or []]


def refresh_organization_metrics(db: Session, organization_id: int) -> int:
    from .adapters import metrics_for
    from .oauth import OAuthService
    from .publishing import access_token_for

    oauth = OAuthService(get_settings())
    rows = db.execute(
        select(Publication, ChannelConnection)
        .join(ChannelConnection, ChannelConnection.id == Publication.connection_id)
        .join(Project, Project.id == Publication.project_id)
        .where(Project.organization_id == organization_id, Publication.simulated.is_(False), Publication.external_id.is_not(None))
    )
    refreshed = 0
    for publication, connection in rows:
        token = access_token_for(connection, oauth)
        if not token:
            continue
        age_hours = (utcnow() - (publication.published_at or publication.created_at)).total_seconds() / 3600
        window = 24 if age_hours < 48 else 168 if age_hours < 24 * 14 else 720
        try:
            values = metrics_for(connection.platform, token).fetch(publication.external_id)
            snapshot = db.scalar(
                select(MetricSnapshot).where(MetricSnapshot.publication_id == publication.id, MetricSnapshot.window_hours == window)
            ) or MetricSnapshot(publication_id=publication.id, window_hours=window)
            for key, value in values.items():
                setattr(snapshot, key, value)
            snapshot.captured_at = utcnow()
            db.add(snapshot)
            if connection.platform == "youtube":
                points = youtube_retention(token, publication.external_id, publication.published_at)
                if points:
                    store_retention(db, publication, points)
                    snapshot.average_view_percentage = round(mean(w for _, w in points) * 100, 1)
            refreshed += 1
        except Exception as exc:  # noqa: BLE001 - one platform error must not stop the rest
            logger.info("Metric refresh failed for publication %s: %s", publication.id, exc)
    db.commit()
    return refreshed


# --- Playbook ------------------------------------------------------------------------------------------------------


def _latest_snapshot(db: Session, publication_id: int) -> MetricSnapshot | None:
    return db.scalar(
        select(MetricSnapshot).where(MetricSnapshot.publication_id == publication_id).order_by(MetricSnapshot.window_hours.desc())
    )


def project_features(db: Session, organization_id: int) -> list[dict[str, Any]]:
    rows = []
    publications = db.scalars(
        select(Publication)
        .join(Project, Project.id == Publication.project_id)
        .where(Project.organization_id == organization_id, Publication.status == "published")
    )
    for publication in publications:
        snapshot = _latest_snapshot(db, publication.id)
        curve = db.scalar(select(RetentionCurve).where(RetentionCurve.publication_id == publication.id))
        retention = None
        if curve and curve.points:
            retention = mean(w for _, w in curve.points)
        elif snapshot and snapshot.average_view_percentage is not None:
            retention = snapshot.average_view_percentage / 100
        if retention is None and not (snapshot and snapshot.views):
            continue
        render = db.get(Render, publication.render_id)
        script = db.get(ScriptVersion, render.script_version_id) if render else None
        timeline = (render.timeline or []) if render else []
        duration = render_duration(render) if render else 0
        shots = [item for item in timeline if item.get("role") != "scene"]
        rows.append(
            {
                "project_id": publication.project_id,
                "title": publication.title,
                "duration": round(duration, 1),
                "shot_seconds": round(duration / len(shots), 2) if shots else None,
                "hook_style": (script.metadata_json or {}).get("hook_style") if script else None,
                "retention": round(retention, 3) if retention is not None else None,
                "views": snapshot.views if snapshot else 0,
                "engagement": round((snapshot.likes + snapshot.comments + snapshot.shares) / snapshot.views, 4)
                if snapshot and snapshot.views
                else 0,
                "drops": [drop.get("role") for drop in (curve.drops if curve else [])],
                "title_question": publication.title.strip().endswith("?"),
                "title_number": bool(re.search(r"\d", publication.title)),
            }
        )
    return rows


def _best_bucket(rows: list[dict], feature: str, buckets: list[tuple[str, Any, Any]], outcome: str = "retention"):
    scored = []
    for label, low, high in buckets:
        values = [row[outcome] for row in rows if row.get(feature) is not None and row.get(outcome) is not None and low <= row[feature] < high]
        if len(values) >= 1:
            scored.append((mean(values), len(values), label))
    if len(scored) < 2:
        return None
    return max(scored)


def _confidence(samples: int) -> float:
    return round(min(0.9, 0.3 + 0.1 * samples), 2)


def derive_rules(rows: list[dict]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if len(rows) < MIN_SAMPLES:
        return rules
    pacing = _best_bucket(rows, "shot_seconds", [("2.5", 0, 2.75), ("3", 2.75, 3.5), ("4", 3.5, 99)])
    if pacing:
        value, samples, label = pacing
        rules.append({"key": "pacing", "value": {"shot_seconds": float(label)},
                      "text": f"Trocar o visual a cada ~{label}s rendeu a melhor retenção média ({value:.0%}).", "confidence": _confidence(samples)})
    duration = _best_bucket(rows, "duration", [("30", 0, 45), ("60", 45, 75), ("90", 75, 9999)])
    if duration:
        value, samples, label = duration
        rules.append({"key": "duration", "value": {"prefer_duration_seconds": int(label)},
                      "text": f"Vídeos de ~{label}s retiveram melhor ({value:.0%} assistido em média).", "confidence": _confidence(samples)})
    styles: dict[str, list[float]] = {}
    for row in rows:
        if row.get("hook_style") and row.get("retention") is not None:
            styles.setdefault(row["hook_style"], []).append(row["retention"])
    if len(styles) >= 2:
        best = max(styles, key=lambda style: mean(styles[style]))
        names = {"question": "pergunta", "statement": "afirmação", "contradiction": "contradição", "reveal": "revelação"}
        rules.append({"key": "hook", "value": {"prefer_hook_style": best},
                      "text": f"Ganchos do tipo {names.get(best, best)} seguraram mais a audiência no início.", "confidence": _confidence(len(styles[best]))})
    drop_roles = [role for row in rows for role in row.get("drops") or [] if role]
    if drop_roles:
        worst = max(set(drop_roles), key=drop_roles.count)
        names = {"hook": "o gancho", "broll": "imagens de apoio", "clip": "clipes", "reveal": "a revelação", "scene": "cenas sem mídia"}
        rules.append({"key": "drops", "value": {"weak_role": worst},
                      "text": f"As maiores quedas acontecem durante {names.get(worst, worst)}: encurte e troque o visual mais cedo nesses trechos.",
                      "confidence": _confidence(drop_roles.count(worst))})
    with_views = [row for row in rows if row.get("views")]
    for feature, label in (("title_question", "em forma de pergunta"), ("title_number", "com números")):
        yes = [math.log1p(row["views"]) for row in with_views if row[feature]]
        no = [math.log1p(row["views"]) for row in with_views if not row[feature]]
        if yes and no:
            better = mean(yes) > mean(no)
            rules.append({"key": f"titles_{feature}", "value": {f"prefer_{feature}": better},
                          "text": f"Títulos {label} tiveram {'mais' if better else 'menos'} visualizações.", "confidence": _confidence(min(len(yes), len(no)))})
    return rules


PLAYBOOK_SYSTEM = """Você é estrategista de um canal de vídeos curtos. A partir da tabela de desempenho (uma linha por vídeo),
escreva até 4 regras práticas e específicas para os próximos roteiros e edições. Não repita as regras já existentes.
Formato JSON: {"rules": [{"key": "ai_<slug>", "text": str, "confidence": 0.0-1.0}]}"""


def update_playbook(db: Session, organization_id: int, actor: str = "learning") -> list[PlaybookRule]:
    rows = project_features(db, organization_id)
    derived = derive_rules(rows)
    result = safe_complete(
        get_ai(),
        PLAYBOOK_SYSTEM,
        json.dumps({"videos": rows[-40:], "regras_existentes": [rule["text"] for rule in derived]}, ensure_ascii=False),
        max_tokens=900,
    ) if len(rows) >= MIN_SAMPLES else None
    if result:
        for item in result.data.get("rules") or []:
            if item.get("text"):
                derived.append({"key": str(item.get("key") or "ai_rule")[:100], "value": {}, "text": str(item["text"])[:500],
                                "confidence": float(item.get("confidence") or 0.5)})
    created = []
    for rule in derived:
        for old in db.scalars(select(PlaybookRule).where(PlaybookRule.organization_id == organization_id, PlaybookRule.key == rule["key"], PlaybookRule.active.is_(True))):
            old.active = False
        row = PlaybookRule(organization_id=organization_id, key=rule["key"], text=rule["text"], value=rule["value"],
                           confidence=rule["confidence"], evidence={"samples": len(rows)})
        db.add(row)
        created.append(row)
    db.flush()
    audit(db, None, "playbook.updated", db.get(Organization, organization_id), actor,
          rules=len(created), samples=len(rows), cost_cents=result.cost_cents if result else 0)
    db.commit()
    return created


def evaluate_experiments(db: Session, organization_id: int) -> int:
    concluded = 0
    experiments = db.scalars(
        select(Experiment)
        .join(Project, Project.id == Experiment.project_id)
        .where(Project.organization_id == organization_id, Experiment.status == "running")
    )
    for experiment in experiments:
        publication = db.scalar(select(Publication).where(Publication.project_id == experiment.project_id, Publication.status == "published"))
        snapshot = _latest_snapshot(db, publication.id) if publication else None
        if not snapshot or snapshot.window_hours < 24:
            continue
        experiment.variants = {**experiment.variants, "result": {"views": snapshot.views, "window_hours": snapshot.window_hours}}
        experiment.status = "concluded"
        concluded += 1
    db.commit()
    return concluded


# --- Topics --------------------------------------------------------------------------------------------------------

TOPIC_SYSTEM = """Você é editor de pauta de um canal de vídeos explicativos curtos. Proponha temas novos com alto potencial
de retenção e busca, dentro do nicho. Use os sinais (vídeos populares do nicho e desempenho do próprio canal) e evite
temas já produzidos ou proibidos. Formato JSON:
{"topics": [{"topic": str, "angle": str, "predicted_score": 0-100, "reason": str}]}"""

FALLBACK_TOPICS = [
    "O que quase ninguém sabe sobre {niche}",
    "{niche} explicado em 60 segundos",
    "3 fatos surpreendentes sobre {niche}",
    "O maior mito sobre {niche}",
    "A história por trás de {niche}",
]


def _own_signals(db: Session, organization_id: int) -> list[dict[str, Any]]:
    rows = project_features(db, organization_id)
    return sorted(rows, key=lambda row: (row.get("retention") or 0, row.get("views") or 0), reverse=True)[:10]


def plan_topics(db: Session, organization: Organization, actor: str, count: int = 8) -> list[TopicSuggestion]:
    from .autopilot import settings_for
    from .research import video_search

    config = settings_for(db, organization.id)
    niche = config.niche.strip() or "curiosidades de ciência e cultura"
    existing = [topic for (topic,) in db.execute(
        select(Brief.topic).join(Project, Project.id == Brief.project_id).where(Project.organization_id == organization.id)
    )] + [topic for (topic,) in db.execute(
        select(TopicSuggestion.topic).where(TopicSuggestion.organization_id == organization.id, TopicSuggestion.status != "rejected")
    )]
    popular: list[dict[str, Any]] = []
    youtube = video_search(get_settings())
    if youtube:
        try:
            popular = [{"title": video.title, "views": video.views, "channel": video.channel} for video in youtube.search(niche, 15, config.language)]
        except Exception as exc:  # noqa: BLE001 - signals are optional
            logger.info("Topic signal search failed: %s", exc)
    result = safe_complete(
        get_ai(),
        TOPIC_SYSTEM,
        json.dumps(
            {
                "nicho": niche,
                "idioma": LANGUAGE_NAME.get(config.language, config.language),
                "publico": config.audience,
                "quantidade": count,
                "populares_no_nicho": popular,
                "melhores_do_canal": _own_signals(db, organization.id),
                "ja_produzidos": existing[-60:],
                "proibidos": list(config.banned_topics or []),
                "playbook": playbook_context(db, organization.id).text,
            },
            ensure_ascii=False,
        ),
        max_tokens=1500,
    )
    if result and result.data.get("topics"):
        ideas = [
            {"topic": str(item.get("topic", "")).strip(), "angle": str(item.get("angle", "")), "score": float(item.get("predicted_score") or 50),
             "reason": str(item.get("reason", "")), "source": {"provider": "ai", "signals": len(popular)}}
            for item in result.data["topics"]
        ]
    elif popular:
        top = max(video["views"] for video in popular) or 1
        ideas = [
            {"topic": re.sub(r"\s*[|#].*$", "", video["title"]).strip(), "angle": "Versão explicativa e mais curta do tema em alta",
             "score": round(40 + 50 * math.log1p(video["views"]) / math.log1p(top), 1), "reason": f"{video['views']} visualizações em {video['channel']}",
             "source": {"provider": "youtube", "title": video["title"]}}
            for video in popular
        ]
    else:
        ideas = [{"topic": template.format(niche=niche), "angle": "", "score": 40 - index, "reason": "Modelo local sem sinais externos",
                  "source": {"provider": "local"}} for index, template in enumerate(FALLBACK_TOPICS)]
    banned = [term.lower() for term in config.banned_topics or [] if term.strip()]
    created: list[TopicSuggestion] = []
    for idea in sorted(ideas, key=lambda item: item["score"], reverse=True):
        topic = idea["topic"][:500]
        if len(topic) < 4 or any(term in topic.lower() for term in banned):
            continue
        if any(similar(topic, other) > 0.8 for other in existing):
            continue
        suggestion = TopicSuggestion(organization_id=organization.id, topic=topic, angle=idea["angle"][:2000],
                                     predicted_score=idea["score"], reason=idea["reason"][:2000], source=idea["source"])
        db.add(suggestion)
        existing.append(topic)
        created.append(suggestion)
        if len(created) >= count:
            break
    db.flush()
    audit(db, None, "topics.planned", organization, actor, created=len(created), cost_cents=result.cost_cents if result else 0)
    db.commit()
    return created


def learning_tick(db: Session, last_runs: dict[str, Any]) -> None:
    """Daily metrics + experiment evaluation, weekly playbook, for every organization with autopilot settings."""
    from .models import AutopilotSettings

    now = utcnow()
    daily = now - last_runs.get("metrics", now - timedelta(days=2)) >= timedelta(hours=24)
    weekly = now - last_runs.get("playbook", now - timedelta(days=8)) >= timedelta(days=7)
    if not (daily or weekly):
        return
    for (organization_id,) in db.execute(select(AutopilotSettings.organization_id)):
        if daily:
            refresh_organization_metrics(db, organization_id)
            evaluate_experiments(db, organization_id)
        if weekly:
            update_playbook(db, organization_id)
    if daily:
        last_runs["metrics"] = now
    if weekly:
        last_runs["playbook"] = now
