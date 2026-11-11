import struct
import zlib

import pytest

from app import ai as ai_module
from app import media as media_module
from app import research as research_module
from app.ai import AIResult
from app.media import Candidate
from app.research import Article, VideoRef


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(width: int = 8, height: int = 8) -> bytes:
    rows = b"".join(b"\x00" + bytes([30, 90, 200]) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")


class FakeAI:
    """Answers each prompt family with deterministic JSON, like the Azure provider would."""

    name = "fake-ai"

    def __init__(self, critic_score: int = 90, safety_ok: bool = True):
        self.critic_score = critic_score
        self.safety_ok = safety_ok
        self.calls: list[str] = []
        self.images_seen = 0

    def complete_json(self, system: str, user: str, images=None, max_tokens: int = 2000) -> AIResult:
        if "dossiê confiável" in system:
            kind, data = "dossier", {
                "summary": "Destiny (2014) é um FPS online da Bungie ambientado no sistema solar.",
                "facts": [
                    {"id": "f1", "text": "Destiny foi lançado em setembro de 2014.", "source_url": "https://example.org/destiny", "timestamp": None},
                    {"id": "f2", "text": "A Torre é o hub social dos Guardiões.", "source_url": "https://example.org/tower", "timestamp": None},
                    {"id": "f3", "text": "O jogo foi desenvolvido pela Bungie.", "source_url": "https://example.org/bungie", "timestamp": None},
                ],
                "angles": ["Por que Destiny mudou os shooters"],
                "hooks": ["Este jogo custou meio bilhão de dólares."],
                "controversies": [],
                "video_moments": [{"video_id": "vid1", "start": 40, "end": 46, "description": "Torre ao amanhecer"}],
            }
        elif "roteirista" in system:
            kind, data = "script", {
                "title": "O jogo de meio bilhão",
                "description": "A história de Destiny.",
                "title_variants": ["Destiny custou meio bilhão?", "3 segredos de Destiny 1"],
                "hook_style": "question",
                "lines": [
                    {"text": "Você sabia que Destiny custou meio bilhão de dólares?", "citations": ["f1"]},
                    {"text": "Lançado em 2014 pela Bungie, ele prometia um universo inteiro.", "citations": ["f1", "f3"]},
                    {"text": "No centro de tudo estava a Torre, o ponto de encontro dos Guardiões.", "citations": ["f2"]},
                    {"text": "Mas a história original foi reescrita meses antes do lançamento.", "citations": []},
                    {"text": "E é por isso que o enredo parecia tão fragmentado.", "citations": []},
                    {"text": "Siga para mais histórias dos bastidores dos games.", "citations": []},
                ],
            }
        elif "editor-chefe" in system:
            kind, data = "critic", {
                "factuality": self.critic_score, "hook": self.critic_score, "pacing": self.critic_score,
                "clarity": self.critic_score, "safety_ok": self.safety_ok, "issues": [] if self.critic_score >= 75 else ["Gancho fraco"],
            }
        elif "planeja o visual" in system:
            kind, data = "queries", {"scenes": [{"position": n, "queries": [f"destiny scene {n}"]} for n in range(1, 10)]}
        elif "editor de vídeo focado em retenção" in system:
            self.images_seen += len(images or [])
            kind, data = "rank", {"scores": [{"index": i, "score": 90 - i, "reason": "relevante"} for i in range(len(images or []))]}
        elif "editor de pauta" in system:
            kind, data = "topics", {"topics": [
                {"topic": "A queda do Destiny 1", "angle": "o que deu errado", "predicted_score": 88, "reason": "alta busca"},
                {"topic": "Destiny 1 queda", "angle": "duplicado", "predicted_score": 70, "reason": "duplicado"},
                {"topic": "Apostas e loot boxes", "angle": "", "predicted_score": 95, "reason": "polêmico"},
                {"topic": "A trilha sonora de Halo", "angle": "", "predicted_score": 60, "reason": "nostalgia"},
            ]}
        elif "estrategista" in system:
            kind, data = "playbook", {"rules": [{"key": "ai_hooks", "text": "Abra com um número concreto.", "confidence": 0.6}]}
        else:
            kind, data = "unknown", {}
        self.calls.append(kind)
        return AIResult(data=data, cost_cents=1, usage={"prompt_tokens": 100, "completion_tokens": 50})

    def transcribe(self, audio):
        return "[0s] transcrição", 1


class FakeMediaSearch:
    name = "pexels"

    def search(self, query: str, limit: int) -> list[Candidate]:
        slug = query.replace(" ", "-")
        return [
            Candidate(provider=self.name, kind="image", url=f"https://img.test/{slug}/{i}.png", thumb=f"https://img.test/{slug}/{i}-t.png",
                      width=1080, height=1920, license="Pexels License", attribution=f"Foto {slug}-{i} (Pexels)",
                      source_url=f"https://pexels.test/{slug}/{i}", title=query)
            for i in range(3)
        ]


class FakeArticles:
    name = "tavily"

    def search(self, query: str, max_results: int) -> list[Article]:
        return [Article(title="Destiny history", url="https://example.org/destiny",
                        content="Destiny was released in September 2014 by Bungie. The Tower is the social hub of the game.")]


class FakeVideos:
    name = "youtube"

    def search(self, query: str, max_results: int, language: str) -> list[VideoRef]:
        return [VideoRef(video_id="vid1", title="Destiny 1 retrospective", channel="Game Lore", views=500_000, duration_seconds=900)]


@pytest.fixture()
def fake_world(monkeypatch):
    fake = FakeAI()
    ai_module.use_provider(fake)
    monkeypatch.setattr(media_module, "search_providers", lambda settings: [FakeMediaSearch()])
    monkeypatch.setattr(media_module, "download", lambda url, max_bytes: (png_bytes(), "image/png"))
    monkeypatch.setattr(research_module, "article_search", lambda settings: FakeArticles())
    monkeypatch.setattr(research_module, "video_search", lambda settings: FakeVideos())
    monkeypatch.setattr(research_module, "fetch_captions", lambda video_id, language: "[40s] A Torre de Destiny ao amanhecer\n[80s] fim")
    yield fake
    ai_module.use_provider(None)
