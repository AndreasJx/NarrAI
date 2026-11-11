from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai as ai_module
from app.models import Approval, Asset, Experiment, Publication, Render, SceneShot, StageRun
from tests.fakes import FakeAI, fake_world  # noqa: F401 - fixture


def test_autopilot_produces_and_publishes_without_humans(client, engine, fake_world):
    project = client.post("/api/v1/autopilot/projects", json={"topic": "Destiny 1", "language": "pt-BR"})
    assert project.status_code == 201, project.text
    project = project.json()
    assert project["autopilot_stage"] == "done", project
    assert project["status"] == "published"
    pid = project["id"]

    dossier = client.get(f"/api/v1/projects/{pid}/dossier").json()
    assert dossier["provider"] == "tavily+youtube+fake-ai"
    assert len(dossier["facts"]) == 3 and dossier["video_moments"][0]["url"].endswith("vid1")

    with Session(engine) as db:
        approvals = list(db.scalars(select(Approval).where(Approval.project_id == pid)))
        assert {a.gate for a in approvals} == {"script", "publish"}
        assert all(a.actor == "autopilot" for a in approvals)
        shots = list(db.scalars(select(SceneShot)))
        assert shots and shots[0].role == "hook"
        assert all(shot.asset_id for shot in shots)
        auto_assets = list(db.scalars(select(Asset).where(Asset.project_id == pid, Asset.kind == "image")))
        assert auto_assets and all(a.metadata_json["license"] == "Pexels License" for a in auto_assets)
        publication = db.scalar(select(Publication).where(Publication.project_id == pid))
        assert publication.status == "published" and publication.simulated
        assert "Créditos:" in publication.description and "(Pexels)" in publication.description
        assert publication.title in {"Destiny custou meio bilhão?", "3 segredos de Destiny 1"}
        assert db.scalar(select(Experiment).where(Experiment.project_id == pid)).status == "running"
        render = db.scalar(select(Render).where(Render.project_id == pid))
        assert render.timeline and render.timeline[0]["role"] == "hook"
        stages = [run.stage for run in db.scalars(select(StageRun).where(StageRun.project_id == pid).order_by(StageRun.id))]
        assert stages == ["research", "script", "script_gate", "media", "render", "render_gate", "publish"]

    assert fake_world.images_seen > 0
    overview = client.get("/api/v1/autopilot/overview").json()
    assert overview["produced"] == 1 and overview["published"] == 1
    assert overview["auto_approval_rate"] == 1.0
    assert {stat["stage"] for stat in overview["stage_stats"] if stat["runs"]} >= {"research", "publish"}


def test_low_score_rewrites_once_then_waits_in_inbox(client, fake_world):
    fake_world.critic_score = 40
    project = client.post("/api/v1/autopilot/projects", json={"topic": "Destiny 1"}).json()
    assert project["autopilot_stage"] == "needs_review"
    assert "script_gate" in project["autopilot_reason"]
    assert fake_world.calls.count("script") == 2

    inbox = client.get("/api/v1/autopilot/inbox").json()
    assert [item["project"]["id"] for item in inbox] == [project["id"]]
    assert inbox[0]["stage"] == "script_gate"

    resumed = client.post(f"/api/v1/projects/{project['id']}/autopilot/resume", json={"approve": True}).json()
    assert resumed["autopilot_stage"] == "done"
    approvals = client.get(f"/api/v1/projects/{project['id']}/approvals").json()
    script_approval = next(a for a in approvals if a["gate"] == "script")
    assert script_approval["actor"] == "ana@example.com"


def test_banned_topic_blocks_without_rewrite(client, fake_world):
    client.put("/api/v1/autopilot/settings", json={"banned_topics": ["meio bilhão"]})
    project = client.post("/api/v1/autopilot/projects", json={"topic": "Destiny 1"}).json()
    assert project["autopilot_stage"] == "needs_review"
    assert "Tema proibido" in project["autopilot_reason"]
    assert fake_world.calls.count("script") == 1


def test_without_ai_heuristic_gate_holds_for_review(client):
    ai_module.use_provider(None)
    project = client.post("/api/v1/autopilot/projects", json={"topic": "Por que o céu é azul"}).json()
    assert project["autopilot_stage"] == "needs_review"
    runs = client.get(f"/api/v1/projects/{project['id']}/autopilot/runs").json()
    gate = [run for run in runs if run["stage"] == "script_gate"]
    assert gate[-1]["status"] == "blocked"
    client.put("/api/v1/autopilot/settings", json={"script_threshold": 40})
    resumed = client.post(f"/api/v1/projects/{project['id']}/autopilot/resume", json={"approve": False}).json()
    assert resumed["autopilot_stage"] == "done"


def test_settings_are_owner_only_and_validated(client, make_client):
    from tests.conftest import signup

    assert client.put("/api/v1/autopilot/settings", json={"press_kit_urls": ["ftp://x"]}).status_code == 422
    updated = client.put("/api/v1/autopilot/settings", json={"enabled": True, "niche": "games clássicos", "cadence_hours": 12}).json()
    assert updated["enabled"] and updated["cadence_hours"] == 12
    client.post("/api/v1/organization/members", json={"email": "ed@example.com", "name": "Ed", "role": "editor", "password": "senha-segura-123"})
    editor = make_client()
    signup_response = editor.post("/api/v1/auth/login", json={"email": "ed@example.com", "password": "senha-segura-123"})
    assert signup_response.status_code == 200
    assert editor.put("/api/v1/autopilot/settings", json={"enabled": False}).status_code == 403
    other = make_client()
    signup(other, "zoe@example.com", "Outra")
    assert other.get("/api/v1/autopilot/settings").json()["enabled"] is False


def test_integrations_report(client):
    report = client.get("/api/v1/autopilot/integrations").json()
    assert report["open_media"] is True
    assert report["ai"] is False and report["queue"] is False


def test_scheduler_tick_starts_one_video_per_cadence(client, engine, fake_world, storage):
    from app import autopilot

    client.put("/api/v1/autopilot/settings", json={"enabled": True, "niche": "games", "cadence_hours": 24})
    with Session(engine) as db:
        started = autopilot.tick(db, storage)
        assert len(started) == 1
        assert autopilot.tick(db, storage) == []
    topics = client.get("/api/v1/autopilot/topics?status=used").json()
    assert len(topics) == 1 and topics[0]["project_id"] == started[0]
