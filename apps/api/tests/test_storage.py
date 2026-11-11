import boto3
from moto import mock_aws

from app.config import Settings
from app.storage import S3Storage

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_local_upload_flow_and_scene_media(client):
    project = client.post("/api/v1/projects", json={"name": "Mídia"}).json()
    pid = project["id"]
    ticket = client.post(
        f"/api/v1/projects/{pid}/uploads",
        json={"filename": "capa.png", "content_type": "image/png", "size_bytes": len(PNG)},
    ).json()
    assert ticket["upload_url"] == f"/api/v1/uploads/{ticket['asset']['id']}/content"
    assert client.put(ticket["upload_url"], content=PNG, headers={"Content-Type": "image/png"}).status_code == 204
    asset = client.post(f"/api/v1/uploads/{ticket['asset']['id']}/complete").json()
    assert asset["status"] == "ready" and asset["size_bytes"] == len(PNG)
    assert client.get(f"/api/v1/assets/{asset['id']}/content").content == PNG

    client.put(f"/api/v1/projects/{pid}/brief", json={"topic": "Cores do céu"})
    script = client.post(f"/api/v1/projects/{pid}/generate/script", json={"estimated_cost_cents": 0}).json()
    scenes = client.post(f"/api/v1/projects/{pid}/generate/storyboard?script_version_id={script['id']}").json()
    scene = client.patch(f"/api/v1/scenes/{scenes[0]['id']}", json={"media_asset_id": asset["id"]}).json()
    assert scene["media_asset_id"] == asset["id"]

    assert client.delete(f"/api/v1/assets/{asset['id']}").status_code == 204
    overview = client.get(f"/api/v1/projects/{pid}/overview").json()
    assert overview["scenes"][0]["media_asset_id"] is None


def test_upload_validation(client):
    pid = client.post("/api/v1/projects", json={"name": "Validação"}).json()["id"]
    unsupported = client.post(
        f"/api/v1/projects/{pid}/uploads",
        json={"filename": "x.exe", "content_type": "application/x-msdownload", "size_bytes": 10},
    )
    assert unsupported.status_code == 422
    too_big = client.post(
        f"/api/v1/projects/{pid}/uploads",
        json={"filename": "x.mp4", "content_type": "video/mp4", "size_bytes": 10**12},
    )
    assert too_big.status_code == 413

    ticket = client.post(
        f"/api/v1/projects/{pid}/uploads",
        json={"filename": "falso.png", "content_type": "image/png", "size_bytes": 12},
    ).json()
    client.put(ticket["upload_url"], content=b"not an image", headers={"Content-Type": "image/png"})
    rejected = client.post(f"/api/v1/uploads/{ticket['asset']['id']}/complete")
    assert rejected.status_code == 422


def test_voice_samples(client, storage, tmp_path):
    voices = client.get("/api/v1/voices").json()
    assert {voice["id"] for voice in voices} >= {"pf_dora", "pm_alex"}
    assert not any(voice["sample_available"] for voice in voices)
    assert client.get("/api/v1/voices/pf_dora/sample").status_code == 404
    assert client.get("/api/v1/voices/../secret/sample").status_code == 404

    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"RIFF0000WAVE")
    storage.put_file(sample, "voices/pf_dora.wav", "audio/wav")
    dora = next(voice for voice in client.get("/api/v1/voices").json() if voice["id"] == "pf_dora")
    assert dora["sample_available"] is True
    assert client.get("/api/v1/voices/pf_dora/sample").content == b"RIFF0000WAVE"


@mock_aws
def test_s3_storage_presigns_and_round_trips(tmp_path):
    settings = Settings(
        s3_endpoint=None,
        s3_public_endpoint=None,
        s3_access_key="test",
        s3_secret_key="test",
        s3_bucket="narra-test",
    )
    storage = S3Storage(settings)
    storage.ensure_bucket()
    assert "narra-test" in [bucket["Name"] for bucket in boto3.client("s3", region_name="us-east-1").list_buckets()["Buckets"]]

    put_url = storage.presign_put("orgs/1/a.png", "image/png")
    assert "narra-test" in put_url and "X-Amz-Signature" in put_url

    source = tmp_path / "a.png"
    source.write_bytes(PNG)
    storage.put_file(source, "orgs/1/a.png", "image/png")
    assert storage.head("orgs/1/a.png") == len(PNG)
    assert storage.read_prefix("orgs/1/a.png", 8) == PNG[:8]
    with storage.local_copy("orgs/1/a.png") as path:
        assert path.read_bytes() == PNG
    assert "X-Amz-Signature" in storage.presign_get("orgs/1/a.png", "image/png")
    storage.delete("orgs/1/a.png")
    assert storage.head("orgs/1/a.png") is None
