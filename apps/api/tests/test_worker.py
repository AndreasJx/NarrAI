import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import worker
from pipeline.worker import render_video, write_subtitles
from video_ai_contracts import RenderRequest, SceneSpec


def test_worker_writes_manifest_when_ffmpeg_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("pipeline.worker.shutil.which", lambda _: None)
    artifact = render_video(RenderRequest(render_id=7, script="Olá\nMundo", output_dir=str(tmp_path)))
    assert artifact.kind == "manifest"
    payload = json.loads(Path(artifact.uri).read_text(encoding="utf-8"))
    assert payload["target"] == {"width": 1080, "height": 1920, "format": "mp4"}
    assert [scene["narration"] for scene in payload["scenes"]] == ["Olá", "Mundo"]


def test_subtitles_cover_the_whole_scene(tmp_path):
    path = tmp_path / "scene.ass"
    write_subtitles(path, "um dois três quatro cinco seis sete oito nove dez", 4.0)
    content = path.read_text(encoding="utf-8")
    dialogues = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == 2
    assert dialogues[0].split(",")[1] == "0:00:00.00"
    assert dialogues[-1].split(",")[2] == "0:00:04.00"


def test_undecodable_media_falls_back_to_generated_background(tmp_path, monkeypatch):
    commands: list[list[str]] = []
    monkeypatch.setattr(worker.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(worker, "load_voice", lambda: None)
    monkeypatch.setattr(worker, "media_decodes", lambda _: False)

    def fake_run(command, **_):
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n")
    render_video(
        RenderRequest(
            render_id=3,
            script="",
            output_dir=str(tmp_path),
            scenes=[SceneSpec(position=1, narration="Cena", duration_seconds=1, media_path=str(broken), media_kind="image")],
        )
    )
    assert str(broken) not in commands[0]
    assert any(arg.startswith("color=") for arg in commands[0])


def test_shots_command_builds_kenburns_crossfades_and_ducked_clip_audio(tmp_path):
    from video_ai_contracts import ShotSpec

    shots = [
        ShotSpec(duration=2.0, media_path="a.png", media_kind="image", effect="zoom_in", role="hook", asset_id=1),
        ShotSpec(duration=3.0, media_path="clip.mp4", media_kind="video", effect="none", role="clip", asset_id=2),
        ShotSpec(duration=1.0, effect="pan_left"),
    ]
    command, timeline = worker._shots_command("ffmpeg", shots, 0, tmp_path / "n.wav", 6.0, tmp_path / "out.mp4", {1})
    graph = command[command.index("-filter_complex") + 1]
    assert "zoompan=z='1+0.15*on/" in graph
    assert graph.count("fps=30,settb=AVTB[v") == 3
    assert "xfade=transition=fade:duration=0.3:offset=2.000[x1]" in graph
    assert "xfade=transition=fade:duration=0.3:offset=5.000[x2]" in graph
    assert "volume=0.25,adelay=2000|2000[c1]" in graph
    assert "amix=inputs=2:duration=first:normalize=0[a]" in graph
    assert "subtitles=scene-0.ass[v]" in graph
    assert command[command.index("-t", command.index("-filter_complex")) + 1] == "6.00"
    assert [(item["start"], item["end"], item["role"]) for item in timeline] == [(0.0, 2.0, "hook"), (2.0, 5.0, "clip"), (5.0, 6.0, "broll")]


def test_shots_scale_to_the_spoken_duration(tmp_path):
    from video_ai_contracts import ShotSpec

    shots = [ShotSpec(duration=2.0, media_path="a.png", media_kind="image"), ShotSpec(duration=2.0, media_path="b.png", media_kind="image")]
    _, timeline = worker._shots_command("ffmpeg", shots, 1, None, 8.0, tmp_path / "out.mp4", set())
    assert timeline[-1]["end"] == 8.0 and timeline[0]["end"] == 4.0


def test_estimated_timeline_for_manifest_renders():
    from pipeline.service import estimated_timeline
    from video_ai_contracts import ShotSpec

    specs = [
        SceneSpec(position=1, narration="a", duration_seconds=4, shots=[ShotSpec(duration=2, role="hook", asset_id=9), ShotSpec(duration=2)]),
        SceneSpec(position=2, narration="b", duration_seconds=3),
    ]
    timeline = estimated_timeline(specs)
    assert [(item["scene"], item["start"], item["end"], item["role"]) for item in timeline] == [
        (1, 0.0, 2.0, "hook"), (1, 2.0, 4.0, "broll"), (2, 4.0, 7.0, "scene")
    ]


class FakeQueue:
    def __init__(self):
        self.items: dict[str, list[dict]] = {}

    def rpush(self, key, value):
        self.items.setdefault(key, []).append(json.loads(value))


def test_stale_renders_are_requeued_or_dead_lettered(client, engine, monkeypatch):
    from datetime import timedelta

    from sqlalchemy.orm import Session

    from app.models import Render, utcnow
    from pipeline import service

    pid = client.post("/api/v1/projects", json={"name": "Órfão"}).json()["id"]
    client.put(f"/api/v1/projects/{pid}/brief", json={"topic": "Render interrompido"})
    script = client.post(f"/api/v1/projects/{pid}/generate/script", json={"estimated_cost_cents": 0}).json()
    old = utcnow() - timedelta(hours=1)
    with Session(engine) as db:
        renders = [
            Render(project_id=pid, script_version_id=script["id"], idempotency_key=f"stale-{n}", status="processing", attempts=n, started_at=old)
            for n in (1, 3)
        ]
        fresh = Render(project_id=pid, script_version_id=script["id"], idempotency_key="fresh", status="processing", attempts=1, started_at=utcnow())
        db.add_all([*renders, fresh])
        db.commit()
        retry_id, dead_id, fresh_id = renders[0].id, renders[1].id, fresh.id

    monkeypatch.setattr(service, "engine", engine)
    queue = FakeQueue()
    service.recover_stale_renders(queue, max_attempts=3)

    assert queue.items[service.RENDER_QUEUE] == [{"render_id": retry_id, "attempt": 2}]
    assert queue.items[service.DEAD_LETTER][0]["payload"] == {"render_id": dead_id}
    with Session(engine) as db:
        assert db.get(Render, retry_id).status == "queued"
        assert db.get(Render, dead_id).status == "failed"
        assert db.get(Render, fresh_id).status == "processing"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_render_video_produces_vertical_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "load_voice", lambda: None)
    progress: list[int] = []
    artifact = render_video(
        RenderRequest(
            render_id=1,
            script="",
            output_dir=str(tmp_path),
            scenes=[
                SceneSpec(position=1, narration="Primeira cena curta", duration_seconds=1),
                SceneSpec(position=2, narration="Segunda cena", duration_seconds=1),
            ],
        ),
        progress.append,
    )
    assert artifact.kind == "video"
    assert Path(artifact.uri).stat().st_size > 0
    assert artifact.metadata["tts"] == "silent"
    assert progress[-1] == 95
