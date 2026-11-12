from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from video_ai_contracts import PublishResult

from app import adapters
from app import main as main_module
from app.channels import access_token_for
from app.config import get_settings
from app.models import ChannelAccount, ChannelConnection, Project, utcnow
from app.oauth import OAuthService

from tests.test_critical_flows import approve, bootstrap, render


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """A developer .env must not leak OAuth apps or the live switch into these tests."""
    for field in ("youtube_client_id", "youtube_client_secret", "tiktok_client_key", "tiktok_client_secret"):
        monkeypatch.setattr(main_module.settings, field, None)
    monkeypatch.setattr(main_module.settings, "allow_live_publish", False)


@pytest.fixture()
def fake_google(monkeypatch):
    calls = {"refresh": 0}

    def exchange(self, platform, code, client):
        assert client.client_id == "org-client" and client.client_secret == "org-secret"
        return {"access_token": f"access-{code}", "refresh_token": "refresh-1", "expires_in": 3600, "scope": "upload"}

    def refresh(self, platform, refresh_token, client):
        calls["refresh"] += 1
        assert refresh_token == "refresh-1"
        return {"access_token": "access-refreshed", "expires_in": 3600}

    monkeypatch.setattr(OAuthService, "exchange", exchange)
    monkeypatch.setattr(OAuthService, "refresh", refresh)
    monkeypatch.setattr(OAuthService, "profile", lambda self, platform, token: ("UC-canal", "Canal da Ana"))
    return calls


def save_youtube(client, **extra):
    body = {"client_id": "org-client", "client_secret": "org-secret", "live_enabled": False, **extra}
    return client.put("/api/v1/platform-credentials/youtube", json=body)


def organization_id(client) -> int:
    return client.get("/api/v1/auth/me").json()["organization"]["id"]


def connect_from_settings(client, code="abc"):
    state = OAuthService(get_settings())._state("youtube", organization_id(client))
    return client.get(f"/api/v1/oauth/callback/youtube?code={code}&state={state}", follow_redirects=False)


def test_owner_registers_oauth_app_without_touching_env(client):
    youtube = client.get("/api/v1/platform-credentials").json()[0]
    assert youtube["source"] == "none" and youtube["redirect_uri"].endswith("/oauth/callback/youtube")
    assert client.get("/api/v1/platforms/youtube/oauth/authorize").status_code == 409

    assert save_youtube(client, client_secret=None).status_code == 422
    saved = save_youtube(client)
    assert saved.status_code == 200, saved.text
    assert saved.json()["source"] == "organization" and saved.json()["has_secret"] is True
    assert "org-secret" not in saved.text

    # Same client id without a secret keeps the stored secret; a new client id requires a new one.
    assert save_youtube(client, client_secret=None, live_enabled=True).json()["live_enabled"] is True
    assert save_youtube(client, client_id="other-client", client_secret=None).status_code == 422

    url = client.get("/api/v1/platforms/youtube/oauth/authorize").json()["authorization_url"]
    params = parse_qs(urlparse(url).query)
    assert params["client_id"] == ["org-client"]
    assert OAuthService(get_settings()).verify_state(params["state"][0], "youtube") == (organization_id(client), None)
    youtube = next(item for item in client.get("/api/v1/platforms").json() if item["id"] == "youtube")
    assert youtube["oauth_configured"] is True and youtube["live_enabled"] is True


def test_env_values_are_only_a_fallback(client, monkeypatch):
    monkeypatch.setattr(main_module.settings, "youtube_client_id", "env-client")
    monkeypatch.setattr(main_module.settings, "youtube_client_secret", "env-secret")
    assert client.get("/api/v1/platform-credentials").json()[0]["source"] == "env"
    save_youtube(client)
    assert client.get("/api/v1/platform-credentials").json()[0]["client_id"] == "org-client"
    assert client.delete("/api/v1/platform-credentials/youtube").status_code == 204
    assert client.get("/api/v1/platform-credentials").json()[0]["source"] == "env"


def test_channel_connected_once_serves_every_project(client, db_session, fake_google):
    save_youtube(client)
    response = connect_from_settings(client)
    assert response.status_code in (302, 307)
    assert response.headers["location"].endswith("/settings?connected=youtube")

    accounts = client.get("/api/v1/channel-accounts").json()
    assert len(accounts) == 1
    account = accounts[0]
    assert account["external_account_id"] == "UC-canal" and account["display_name"] == "Canal da Ana"
    assert account["authorized"] and account["can_refresh"] and account["projects"] == 0

    for name in ("Primeiro", "Segundo"):
        project = client.post("/api/v1/projects", json={"name": name}).json()
        linked = client.post(f"/api/v1/projects/{project['id']}/connections", json={"platform": "youtube", "account_id": account["id"]})
        assert linked.status_code == 201, linked.text
        assert linked.json()["authorized"] is True and linked.json()["display_name"] == "Canal da Ana"
    assert client.get("/api/v1/channel-accounts").json()[0]["projects"] == 2

    # Reconnecting the same channel updates the shared tokens instead of creating a duplicate.
    connect_from_settings(client, code="again")
    assert len(client.get("/api/v1/channel-accounts").json()) == 1
    stored = db_session.get(ChannelAccount, account["id"])
    db_session.refresh(stored)
    assert OAuthService(get_settings()).decrypt(stored.config["access_token_encrypted"]) == "access-again"

    assert client.delete(f"/api/v1/channel-accounts/{account['id']}").status_code == 204
    overview = client.get(f"/api/v1/projects/{project['id']}/overview").json()
    assert overview["connections"][0]["authorized"] is False


def test_autopilot_reuses_the_organization_account(client, db_session, fake_google):
    from app.autopilot import _connection

    save_youtube(client)
    connect_from_settings(client)
    project = db_session.get(Project, client.post("/api/v1/projects", json={"name": "Auto"}).json()["id"])
    connection = _connection(db_session, project, "youtube")
    assert connection.platform == "youtube" and connection.account_id is not None
    assert connection.config == {}


def test_expired_token_is_refreshed_and_persisted(client, db_session, fake_google):
    save_youtube(client)
    connect_from_settings(client)
    project = client.post("/api/v1/projects", json={"name": "Refresh"}).json()
    account_id = client.get("/api/v1/channel-accounts").json()[0]["id"]
    linked = client.post(f"/api/v1/projects/{project['id']}/connections", json={"platform": "youtube", "account_id": account_id}).json()

    account = db_session.get(ChannelAccount, account_id)
    account.config = {**account.config, "expires_at": (utcnow() - timedelta(minutes=5)).isoformat()}
    db_session.commit()

    connection = db_session.get(ChannelConnection, linked["id"])
    assert access_token_for(db_session, connection, get_settings()) == "access-refreshed"
    db_session.commit()
    assert access_token_for(db_session, connection, get_settings()) == "access-refreshed"
    assert fake_google["refresh"] == 1
    assert account.config["refresh_token_encrypted"]


def test_live_publish_is_enabled_per_platform_in_the_ui(client, fake_google, monkeypatch):
    sent = []

    def publish(self, request):
        sent.append(self.token)
        return PublishResult(external_id="yt-123", url="https://youtu.be/yt-123", simulated=False)

    monkeypatch.setattr(adapters.YouTubePublisher, "publish", publish)
    save_youtube(client)
    connect_from_settings(client)
    project, script = bootstrap(client)
    pid = project["id"]
    approve(client, pid, "script", script["id"])
    rendered = render(client, pid, script["id"], key="render-live").json()
    approve(client, pid, "publish", rendered["id"])
    account_id = client.get("/api/v1/channel-accounts").json()[0]["id"]
    connection = client.post(f"/api/v1/projects/{pid}/connections", json={"platform": "youtube", "account_id": account_id}).json()
    payload = {"render_id": rendered["id"], "connection_id": connection["id"], "title": "Real", "live": True}

    blocked = client.post(f"/api/v1/projects/{pid}/publications", json={**payload, "idempotency_key": "live-1"})
    assert blocked.status_code == 400 and "Configurações" in blocked.json()["detail"]

    save_youtube(client, client_secret=None, live_enabled=True)
    published = client.post(f"/api/v1/projects/{pid}/publications", json={**payload, "idempotency_key": "live-2"})
    assert published.status_code == 201, published.text
    assert published.json()["simulated"] is False and published.json()["status"] == "processing"
    assert sent == ["access-abc"]
