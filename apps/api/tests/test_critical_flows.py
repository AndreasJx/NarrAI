from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.models import Publication, utcnow
from app.oauth import OAuthService
from app.publishing import run_due_publications


def bootstrap(client, budget=500):
    project = client.post("/api/v1/projects", json={"name": "MVP", "budget_cents": budget}).json()
    client.put(
        f"/api/v1/projects/{project['id']}/brief",
        json={"topic": "IA responsável", "audience": "criadores", "objective": "educar"},
    )
    script = client.post(
        f"/api/v1/projects/{project['id']}/generate/script",
        json={"estimated_cost_cents": 10},
    ).json()
    return project, script


def approve(client, project_id, gate, target_id):
    response = client.post(
        f"/api/v1/projects/{project_id}/approvals",
        json={"gate": gate, "target_id": target_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def render(client, project_id, script_id, key="render-001", cost=100):
    return client.post(
        f"/api/v1/projects/{project_id}/renders",
        json={"script_version_id": script_id, "idempotency_key": key, "estimated_cost_cents": cost},
    )


def test_render_requires_approval_and_is_idempotent(client):
    project, script = bootstrap(client)
    assert render(client, project["id"], script["id"]).status_code == 409

    approval = approve(client, project["id"], "script", script["id"])
    assert approval["actor"] == "ana@example.com"
    first = render(client, project["id"], script["id"])
    second = render(client, project["id"], script["id"])
    assert first.status_code == 201
    assert first.json()["status"] == "completed"
    assert second.json()["id"] == first.json()["id"]
    assert client.get(f"/api/v1/projects/{project['id']}").json()["spent_cents"] == 110


def test_full_flow_until_simulated_publication(client):
    project, script = bootstrap(client)
    pid = project["id"]
    assert client.post(f"/api/v1/projects/{pid}/generate/research", json={"estimated_cost_cents": 5}).status_code == 200

    edited = client.put(
        f"/api/v1/projects/{pid}/scripts/{script['id']}",
        json={"content": "Abertura com pergunta.\nExplicação curta.\nChamada final."},
    )
    assert edited.status_code == 201
    edited = edited.json()
    assert edited["version"] == 2 and edited["author"] == "ana@example.com"

    scenes = client.post(f"/api/v1/projects/{pid}/generate/storyboard?script_version_id={edited['id']}").json()
    assert [scene["narration"] for scene in scenes] == ["Abertura com pergunta.", "Explicação curta.", "Chamada final."]
    patched = client.patch(f"/api/v1/scenes/{scenes[0]['id']}", json={"narration": "Nova abertura", "duration_seconds": 4})
    assert patched.json()["narration"] == "Nova abertura"

    approve(client, pid, "script", edited["id"])
    rendered = render(client, pid, edited["id"], key="render-flow").json()
    assert rendered["status"] == "completed" and rendered["progress"] == 100

    preview = client.get(f"/api/v1/renders/{rendered['id']}/preview").json()
    assert preview["url"] == f"/api/v1/renders/{rendered['id']}/content"
    assert client.get(preview["url"]).status_code == 200

    connection = client.post(
        f"/api/v1/projects/{pid}/connections",
        json={"platform": "youtube", "external_account_id": "canal-simulado"},
    ).json()
    assert connection["authorized"] is False
    payload = {
        "render_id": rendered["id"],
        "connection_id": connection["id"],
        "title": "Teste",
        "idempotency_key": "publish-001",
    }
    assert client.post(f"/api/v1/projects/{pid}/publications", json=payload).status_code == 409
    approve(client, pid, "publish", rendered["id"])
    publication = client.post(f"/api/v1/projects/{pid}/publications", json=payload)
    assert publication.status_code == 201
    assert publication.json()["simulated"] is True
    assert publication.json()["status"] == "published"

    live = client.post(
        f"/api/v1/projects/{pid}/publications",
        json={**payload, "idempotency_key": "publish-live", "live": True},
    )
    assert live.status_code == 400

    metric = client.post(
        f"/api/v1/publications/{publication.json()['id']}/metrics",
        json={"views": 1000, "likes": 20, "comments": 5, "shares": 5},
    )
    assert metric.status_code == 201
    insight = client.post(f"/api/v1/projects/{pid}/insights").json()
    assert "CTA" in insight["text"]

    overview = client.get(f"/api/v1/projects/{pid}/overview").json()
    assert overview["project"]["status"] == "published"
    assert overview["latest_script"]["version"] == 2
    assert overview["latest_render"]["id"] == rendered["id"]
    assert len(overview["publications"]) == 1

    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["project_count"] == 1
    assert dashboard["published_count"] == 1
    assert dashboard["spent_cents"] == 115
    assert dashboard["latest_insight"]["id"] == insight["id"]

    calendar = client.get("/api/v1/calendar").json()
    assert calendar[0]["platform"] == "youtube" and calendar[0]["project_name"] == "MVP"
    statuses = [event["payload"].get("current") for event in client.get(f"/api/v1/projects/{pid}/audit").json()]
    assert "published" in statuses


def test_scheduled_publication_runs_when_due(client, engine, storage, db_session):
    project, script = bootstrap(client)
    pid = project["id"]
    approve(client, pid, "script", script["id"])
    rendered = render(client, pid, script["id"], key="render-schedule").json()
    approve(client, pid, "publish", rendered["id"])
    connection = client.post(
        f"/api/v1/projects/{pid}/connections", json={"platform": "tiktok", "external_account_id": "perfil"}
    ).json()
    when = (datetime.now(timezone(timedelta(hours=-3))) + timedelta(hours=2)).isoformat()
    scheduled = client.post(
        f"/api/v1/projects/{pid}/publications",
        json={
            "render_id": rendered["id"],
            "connection_id": connection["id"],
            "title": "Agendado",
            "idempotency_key": "publish-later",
            "scheduled_at": when,
        },
    ).json()
    assert scheduled["status"] == "scheduled"

    row = db_session.get(Publication, scheduled["id"])
    row.scheduled_at = utcnow() - timedelta(minutes=1)
    db_session.commit()
    assert run_due_publications(db_session, storage, Settings()) == 1
    db_session.refresh(row)
    assert row.status == "published"


def test_budget_is_enforced(client):
    project, _ = bootstrap(client, budget=10)
    response = client.post(
        f"/api/v1/projects/{project['id']}/generate/research",
        json={"estimated_cost_cents": 1},
    )
    assert response.status_code == 402


def test_oauth_state_and_credentials_are_signed_and_encrypted():
    service = OAuthService(Settings(credential_secret="a-long-local-test-secret"))
    assert service.verify_state(service._state("youtube", 7, 42), "youtube") == (7, 42)
    assert service.verify_state(service._state("youtube", 7), "youtube") == (7, None)
    # Signatures are binary and often contain b"."; every one of them must still verify.
    assert all(service.verify_state(service._state("youtube", n, n), "youtube") == (n, n) for n in range(300))

    encrypted = service.encrypt("access-token")
    assert encrypted != "access-token"
    assert service.decrypt(encrypted) == "access-token"
