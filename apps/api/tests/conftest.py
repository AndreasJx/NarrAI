import os

# A real config/azure-openai.json on the developer machine must never reach the tests.
os.environ["AZURE_OPENAI_CONFIG_FILE"] = "tests/__no_azure_config__.json"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import main as main_module  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.storage import LocalStorage, get_storage  # noqa: E402

app = main_module.app


@pytest.fixture(autouse=True)
def no_external_media(monkeypatch):
    """Open media sources need no key, so tests must never reach them."""
    from app import media as media_module

    monkeypatch.setattr(media_module, "search_providers", lambda settings: [])


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def storage(tmp_path):
    return LocalStorage(tmp_path / "storage")


@pytest.fixture()
def make_client(engine, storage, tmp_path, monkeypatch):
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(main_module.settings, "redis_url", None)
    monkeypatch.setattr(main_module.settings, "artifact_dir", tmp_path)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_storage] = lambda: storage
    clients: list[TestClient] = []

    def build() -> TestClient:
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)
    app.dependency_overrides.clear()


def signup(client: TestClient, email: str = "ana@example.com", organization: str = "Estúdio Ana") -> dict:
    response = client.post(
        "/api/v1/auth/signup",
        json={"name": "Ana", "email": email, "password": "senha-segura-123", "organization_name": organization},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def client(make_client):
    client = make_client()
    signup(client)
    return client


@pytest.fixture()
def db_session(engine):
    with Session(engine) as session:
        yield session
