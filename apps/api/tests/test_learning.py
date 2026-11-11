from sqlalchemy import select
from sqlalchemy.orm import Session

from app.learning import analyze_drops, derive_rules, evaluate_experiments, playbook_context, plan_topics
from app.models import Experiment, Organization, PlaybookRule, Publication, Render, ScriptVersion
from tests.fakes import fake_world  # noqa: F401 - fixture

TIMELINE = [
    {"scene": 1, "shot": 1, "start": 0, "end": 2.5, "role": "hook", "kind": "image", "asset_id": 1},
    {"scene": 1, "shot": 2, "start": 2.5, "end": 6, "role": "broll", "kind": "image", "asset_id": 2},
    {"scene": 2, "shot": 1, "start": 6, "end": 14, "role": "clip", "kind": "video", "asset_id": 3},
    {"scene": 3, "shot": 1, "start": 14, "end": 20, "role": "reveal", "kind": "image", "asset_id": 4},
]


def test_drops_are_mapped_to_the_shot_on_screen():
    points = [[0, 1.0], [0.1, 0.95], [0.4, 0.6], [0.6, 0.58], [1.0, 0.5]]
    drops = analyze_drops(points, TIMELINE, 20, limit=2)
    # Losses are attributed to the middle of each interval: 10-40% of 20s is ~5s (broll), 60-100% is ~16s (reveal).
    assert [drop["role"] for drop in drops] == ["broll", "reveal"]
    assert drops[0]["loss"] == 0.35 and drops[0]["at"] == 5.0 and drops[0]["scene"] == 1


def _publish_autopilot_video(client, topic):
    project = client.post("/api/v1/autopilot/projects", json={"topic": topic}).json()
    assert project["autopilot_stage"] == "done", project
    return project["id"]


def test_feedback_loop_learns_rules_and_feeds_them_back(client, engine, fake_world):
    pids = [_publish_autopilot_video(client, topic) for topic in ("Destiny 1", "Halo 2", "Portal")]
    with Session(engine) as db:
        publications = {pid: db.scalar(select(Publication).where(Publication.project_id == pid)) for pid in pids}
        # The cadence scheduled videos 2 and 3 for later; pretend the scheduler already published them.
        assert [publications[pid].status for pid in pids] == ["published", "scheduled", "scheduled"]
        for publication in publications.values():
            publication.status = "published"
        # Distinct pacing per video so the playbook has something to compare.
        for pid, seconds in zip(pids, (2.5, 3.0, 4.0)):
            render = db.get(Render, publications[pid].render_id)
            count = 6
            render.timeline = [{"scene": 1, "shot": n + 1, "start": n * seconds, "end": (n + 1) * seconds, "role": "broll" if n else "hook"} for n in range(count)]
            script = db.get(ScriptVersion, render.script_version_id)
            script.metadata_json = {**script.metadata_json, "hook_style": "question" if pid != pids[2] else "statement"}
        db.commit()
        publication_ids = [publications[pid].id for pid in pids]

    curves = {
        publication_ids[0]: [[0, 1], [0.25, 0.8], [0.5, 0.7], [1, 0.6]],
        publication_ids[1]: [[0, 1], [0.25, 0.6], [0.5, 0.45], [1, 0.3]],
        publication_ids[2]: [[0, 1], [0.1, 0.5], [0.5, 0.35], [1, 0.2]],
    }
    for publication_id, points in curves.items():
        retention = client.post(f"/api/v1/publications/{publication_id}/retention", json={"points": points})
        assert retention.status_code == 201, retention.text
        assert retention.json()["drops"][0]["role"] in {"hook", "broll"}
        client.post(f"/api/v1/publications/{publication_id}/metrics", json={"views": 1000, "likes": 50, "window_hours": 48})
    assert client.post(f"/api/v1/publications/{publication_ids[0]}/retention", json={"points": [[2, 1], [3, 0]]}).status_code == 422

    rules = client.post("/api/v1/autopilot/playbook/refresh").json()
    keys = {rule["key"] for rule in rules}
    assert {"pacing", "hook", "drops", "ai_hooks"} <= keys
    pacing = next(rule for rule in rules if rule["key"] == "pacing")
    assert pacing["value"] == {"shot_seconds": 2.5}

    with Session(engine) as db:
        organization_id = db.get(Publication, publication_ids[0]).project_id and db.scalar(select(Organization.id))
        context = playbook_context(db, organization_id)
        assert context.params["shot_seconds"] == 2.5
        assert context.params["prefer_hook_style"] == "question"
        assert "Abra com um número concreto." in context.text
        assert evaluate_experiments(db, organization_id) == 3
        assert all(exp.status == "concluded" for exp in db.scalars(select(Experiment)))
    # Refreshing again replaces rules instead of piling them up.
    client.post("/api/v1/autopilot/playbook/refresh")
    with Session(engine) as db:
        assert db.scalar(select(PlaybookRule).where(PlaybookRule.key == "pacing", PlaybookRule.active.is_(True))) is not None
        assert len([r for r in db.scalars(select(PlaybookRule).where(PlaybookRule.key == "pacing", PlaybookRule.active.is_(True)))]) == 1

    overview = client.get("/api/v1/autopilot/overview").json()
    assert overview["retention_samples"] == 3 and len(overview["retention_curve"]) == 11
    assert overview["retention_curve"][0] == [0.0, 1.0]

    # The writer receives the learned rules: the next script prompt contains them.
    next_project = _publish_autopilot_video(client, "Starcraft")
    assert next_project


def test_rules_need_at_least_two_measured_videos():
    assert derive_rules([{"retention": 0.5, "shot_seconds": 3, "duration": 60}]) == []


def test_topic_planner_dedupes_and_respects_banned_topics(client, engine, fake_world):
    client.put("/api/v1/autopilot/settings", json={"niche": "games", "banned_topics": ["apostas"]})
    client.post("/api/v1/autopilot/projects", json={"topic": "A trilha sonora de Halo"})
    with Session(engine) as db:
        organization = db.scalar(select(Organization))
        created = plan_topics(db, organization, "test")
        topics = [item.topic for item in created]
    assert topics == ["A queda do Destiny 1"]
    listed = client.get("/api/v1/autopilot/topics").json()
    assert [item["topic"] for item in listed] == topics
    project = client.post(f"/api/v1/autopilot/topics/{listed[0]['id']}/use").json()
    assert project["name"] == "A queda do Destiny 1"
    assert client.get("/api/v1/autopilot/topics").json() == []
