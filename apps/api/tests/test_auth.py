from tests.conftest import signup


def test_signup_login_me_and_logout(make_client):
    client = make_client()
    me = signup(client)
    assert me["role"] == "owner"
    assert me["organization"]["name"] == "Estúdio Ana"
    assert client.get("/api/v1/auth/me").json()["user"]["email"] == "ana@example.com"

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    bad = client.post("/api/v1/auth/login", json={"email": "ana@example.com", "password": "errada-123"})
    assert bad.status_code == 401
    good = client.post("/api/v1/auth/login", json={"email": "ANA@example.com", "password": "senha-segura-123"})
    assert good.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_duplicate_signup_is_rejected(make_client):
    client = make_client()
    signup(client)
    response = client.post(
        "/api/v1/auth/signup",
        json={"name": "Outra", "email": "ana@example.com", "password": "senha-segura-123", "organization_name": "X"},
    )
    assert response.status_code == 409


def test_endpoints_require_authentication(make_client):
    client = make_client()
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/projects").status_code == 401
    assert client.post("/api/v1/projects", json={"name": "x"}).status_code == 401


def test_organizations_are_isolated(make_client):
    ana = make_client()
    bruno = make_client()
    signup(ana)
    signup(bruno, email="bruno@example.com", organization="Estúdio Bruno")
    project = ana.post("/api/v1/projects", json={"name": "Privado"}).json()

    assert bruno.get(f"/api/v1/projects/{project['id']}").status_code == 404
    assert bruno.get(f"/api/v1/projects/{project['id']}/overview").status_code == 404
    assert bruno.put(f"/api/v1/projects/{project['id']}/brief", json={"topic": "invasão"}).status_code == 404
    assert bruno.get("/api/v1/projects").json() == []
    assert len(ana.get("/api/v1/projects").json()) == 1


def test_roles_restrict_actions(make_client):
    owner = make_client()
    viewer = make_client()
    signup(owner)
    added = owner.post(
        "/api/v1/organization/members",
        json={"email": "leitor@example.com", "name": "Leitor", "role": "viewer", "password": "senha-leitor-123"},
    )
    assert added.status_code == 201
    project = owner.post("/api/v1/projects", json={"name": "Equipe"}).json()

    login = viewer.post("/api/v1/auth/login", json={"email": "leitor@example.com", "password": "senha-leitor-123"})
    assert login.json()["role"] == "viewer"
    assert viewer.get(f"/api/v1/projects/{project['id']}").status_code == 200
    assert viewer.post("/api/v1/projects", json={"name": "Não pode"}).status_code == 403
    assert viewer.patch("/api/v1/organization", json={"name": "Hack"}).status_code == 403

    members = owner.get("/api/v1/organization/members").json()
    owner_id = next(item["user_id"] for item in members if item["role"] == "owner")
    assert owner.patch(f"/api/v1/organization/members/{owner_id}", json={"role": "editor"}).status_code == 409
