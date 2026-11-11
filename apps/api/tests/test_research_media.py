from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai as ai_module
from app.adapters import VOICE_LANGUAGE, voice_for
from app.config import Settings
from app.gates import heuristic_script_review, rights_review
from app.media import Candidate, rank_candidates, sniff_type, visual_queries
from app.models import Asset, Scene, SceneShot, ScriptVersion, Source
from app.retention import credits_for, plan_shots, with_credits
from pipeline.tts import kokoro_lang
from tests.fakes import fake_world, png_bytes  # noqa: F401 - fixture


def _project_with_script(client, topic="Destiny 1", language="pt-BR"):
    pid = client.post("/api/v1/projects", json={"name": topic, "language": language}).json()["id"]
    client.put(f"/api/v1/projects/{pid}/brief", json={"topic": topic, "language": language, "constraints": {"duration_seconds": 60}})
    return pid


def test_research_collects_articles_videos_and_cited_dossier(client, engine, fake_world):
    pid = _project_with_script(client)
    assert client.post(f"/api/v1/projects/{pid}/research/jobs").json() == {"queued": False}
    dossier = client.get(f"/api/v1/projects/{pid}/dossier").json()
    assert dossier["facts"][0]["source_url"].startswith("https://")
    with Session(engine) as db:
        providers = [source.provider for source in db.scalars(select(Source).where(Source.project_id == pid))]
    assert providers.count("tavily") == 1 and providers.count("youtube") == 1
    script = client.post(f"/api/v1/projects/{pid}/generate/script", json={"estimated_cost_cents": 0}).json()
    assert script["author"] == "fake-ai"
    assert script["metadata_json"]["citations"][1] == ["f1", "f3"]
    project = client.get(f"/api/v1/projects/{pid}").json()
    assert project["spent_cents"] == 2


def test_local_fallback_speaks_the_project_language(client):
    pid = _project_with_script(client, "Why is the sky blue", "en-US")
    client.post(f"/api/v1/projects/{pid}/generate/research", json={"estimated_cost_cents": 0})
    script = client.post(f"/api/v1/projects/{pid}/generate/script", json={"estimated_cost_cents": 0}).json()
    assert script["content"].startswith("Have you ever wondered")
    assert client.get(f"/api/v1/projects/{pid}/dossier").json()["provider"] == "local"


def test_voices_per_language():
    assert kokoro_lang("pf_dora") == "pt-br" and kokoro_lang("am_michael") == "en-us" and kokoro_lang("bf_emma") == "en-gb"
    org = SimpleNamespace(voice="pm_alex", voices={"en-GB": "bm_george"})
    assert voice_for(org, "pt-BR") == "pm_alex"
    assert voice_for(org, "en-GB") == "bm_george"
    assert voice_for(org, "en-US") == "af_heart"
    assert {VOICE_LANGUAGE[v] for v in VOICE_LANGUAGE} == {"pt-BR", "en-US", "en-GB"}


def test_owner_picks_one_voice_per_language(client):
    voices = client.get("/api/v1/voices").json()
    assert {voice["language"] for voice in voices} == {"pt-BR", "en-US", "en-GB"}
    client.patch("/api/v1/organization", json={"voice": "bm_fable"})
    organization = client.patch("/api/v1/organization", json={"voice": "pm_santa"}).json()
    assert organization["voices"] == {"en-GB": "bm_fable", "pt-BR": "pm_santa"}
    assert client.patch("/api/v1/organization", json={"voice": "xx_fake"}).status_code == 422


def test_auto_media_stores_licensed_assets_and_plans_shots(client, engine, fake_world):
    pid = _project_with_script(client)
    script = client.post(f"/api/v1/projects/{pid}/generate/script", json={"estimated_cost_cents": 0}).json()
    summary = client.post(f"/api/v1/projects/{pid}/media/auto", params={"script_version_id": script["id"]}).json()
    assert summary["queued"] is False and summary["scenes_with_media"] == summary["scenes"] == 6
    shots = client.get(f"/api/v1/projects/{pid}/shots", params={"script_version_id": script["id"]}).json()
    assert shots[0]["role"] == "hook" and shots[0]["duration"] <= 2.5
    assert {shot["effect"] for shot in shots} <= {"zoom_in", "zoom_out", "pan_left", "pan_right"}
    credits = client.get(f"/api/v1/projects/{pid}/credits", params={"script_version_id": script["id"]}).json()
    assert credits and all("(Pexels)" in credit for credit in credits)
    overview = client.get(f"/api/v1/projects/{pid}/overview").json()
    assert all(asset["metadata_json"]["origin"] == "auto" for asset in overview["assets"])


def test_plan_shots_rules(engine):
    with Session(engine) as db:
        script = ScriptVersion(project_id=1, version=1, content="x")
        from app.models import Organization, Project

        db.add(Organization(name="o"))
        db.flush()
        db.add(Project(organization_id=1, name="p"))
        db.flush()
        db.add(script)
        db.flush()
        scenes = [Scene(script_version_id=script.id, position=n, narration=f"cena {n}", visual_prompt="", duration_seconds=6) for n in range(1, 6)]
        db.add_all(scenes)
        db.flush()

        def asset(score, kind="image", **meta):
            item = Asset(project_id=1, kind=kind, uri=f"k{score}", status="ready", metadata_json={"score": score, "origin": "auto", "license": "L", "attribution": f"A{score}", **meta})
            db.add(item)
            db.flush()
            return item

        by_scene = {scene.id: [asset(10 * scene.position), asset(10 * scene.position + 1)] for scene in scenes}
        best = asset(99)
        by_scene[scenes[2].id].append(best)
        clip_a = asset(50, "video", fair_use=True, duration=8)
        clip_b = asset(51, "video", fair_use=True, duration=8)
        plan = plan_shots(db, scenes, by_scene, {scenes[1].id: clip_a, scenes[3].id: clip_b}, {"shot_seconds": 3}, 8, 0.2)

        first = [shot for shot in plan.shots if shot.scene_id == scenes[0].id]
        assert first[0].role == "hook" and first[0].asset_id == best.id and first[0].duration == 2.5
        assert sum(shot.duration for shot in first) == 6
        assert [shot.role for shot in plan.shots].count("clip") == 1 and plan.dropped_clips == 1
        assert plan.fair_use_seconds <= 0.2 * 30
        assert any(shot.role == "reveal" for shot in plan.shots)
        assert all(2 <= shot.duration <= 6 for shot in plan.shots)

        issues, detail = rights_review(db, script.id, Settings(fair_use_max_ratio=0.1))
        assert any("clipes de terceiros" in issue for issue in issues) and detail["fair_use_seconds"] == 6
        credits = credits_for(db, script.id)
        assert "A99" in credits and len(credits) == len(set(credits))
        assert with_credits("Descrição", credits).startswith("Descrição\n\nCréditos:\n- ")
        assert with_credits("Já tem\nCréditos:\n- x", credits) == "Já tem\nCréditos:\n- x"
        assert db.scalars(select(SceneShot)).first() is not None


def test_ranking_and_queries_without_ai():
    ai_module.use_provider(None)
    candidates = [
        Candidate(provider="wikimedia", kind="image", url="u1", thumb="t1", width=800, height=600, title="cat sleeping"),
        Candidate(provider="pexels", kind="image", url="u2", thumb="t2", width=1080, height=1920, title="Destiny Tower guardian"),
    ]
    ranked, cost = rank_candidates(None, "A Torre dos Guardiões em Destiny", "Destiny Tower", candidates)
    assert ranked[0].url == "u2" and cost == 0
    scenes = [SimpleNamespace(position=1, narration="A Torre é o hub social dos Guardiões"), SimpleNamespace(position=2, narration="Fim")]
    queries, _ = visual_queries(None, "Destiny 1", scenes)
    assert set(queries) == {1, 2} and all(queries[1])


def test_sniff_type_rejects_disguised_files():
    assert sniff_type(png_bytes(), "image/jpeg") == "image/png"
    assert sniff_type(b"<html>not an image</html>", "image/png") is None


def test_heuristic_review_rewards_hook_length_and_sources():
    lines = ["Por que o céu é azul?"] + ["Uma frase explicativa curta com cerca de doze palavras para medir o tamanho."] * 11 + ["Siga para mais."]
    script = ScriptVersion(project_id=1, version=1, content="\n".join(lines))
    dossier = SimpleNamespace(facts=[{}, {}, {}])
    review = heuristic_script_review(script, dossier, 60)
    assert review.score == 90 and not review.issues
    long_opening = "Olá a todos, sejam muito bem-vindos ao canal, hoje vamos falar de um tema muito interessante e importante."
    weak = heuristic_script_review(ScriptVersion(project_id=1, version=1, content=long_opening), None, 60)
    assert weak.score < 50 and len(weak.issues) >= 3
