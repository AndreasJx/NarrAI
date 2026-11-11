import hashlib
import json
from pathlib import Path

import httpx

from video_ai_contracts import Artifact, GenerationResult, PublishRequest, PublishResult

from .config import Settings


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


LOCAL_TEMPLATES = {
    "pt": {
        "hook": "Você já se perguntou: {topic}?",
        "body": [
            "Primeiro, o contexto: de onde vem essa pergunta e por que ela importa no dia a dia.",
            "Agora o mecanismo principal, explicado passo a passo e sem jargão.",
            "Um exemplo concreto ajuda a fixar a ideia.",
            "Atenção a um equívoco comum que confunde muita gente.",
            "O que a evidência disponível diz, com suas limitações.",
            "Como aplicar isso na prática ainda hoje.",
        ],
        "wrap": "Resumindo: {topic} tem explicação, e agora você sabe qual é.",
        "cta": "Siga para mais explicações curtas como esta.",
    },
    "en": {
        "hook": "Have you ever wondered: {topic}?",
        "body": [
            "First, the context: where this question comes from and why it matters.",
            "Now the core mechanism, step by step and without jargon.",
            "A concrete example makes the idea stick.",
            "Watch out for a common misconception that trips people up.",
            "What the available evidence says, and its limits.",
            "How you can use this today.",
        ],
        "wrap": "In short: {topic} has an explanation, and now you know it.",
        "cta": "Follow for more short explainers like this one.",
    },
}


class LocalLLM:
    """Deterministic script template used when no AI provider is configured."""

    def generate(
        self, topic: str, audience: str, context: str, duration_seconds: int, language: str = "pt-BR"
    ) -> GenerationResult:
        seed = stable_id(f"{topic}|{audience}|{context}|{language}")
        topic = topic.strip().rstrip("?.!")
        template = LOCAL_TEMPLATES["en" if language.startswith("en") else "pt"]
        points = max(2, min(6, duration_seconds // 15))
        lines = [
            template["hook"].format(topic=topic),
            *template["body"][:points],
            template["wrap"].format(topic=topic),
            template["cta"],
        ]
        return GenerationResult(
            text="\n".join(lines),
            metadata={"provider": "local", "seed": seed, "audience": audience, "language": language},
        )


class LocalResearch:
    def research(self, topic: str) -> GenerationResult:
        seed = stable_id(topic)
        return GenerationResult(
            text=(
                f"Pesquisa local sobre {topic}: contexto histórico, mecanismo principal, exemplo cotidiano "
                "e ressalvas. Revise e substitua por fontes verificáveis antes de publicar."
            ),
            metadata={"provider": "local", "seed": seed},
        )


LANGUAGES = ("pt-BR", "en-US", "en-GB")

KOKORO_VOICES = [
    {"id": "pf_dora", "label": "Dora", "language": "pt-BR", "gender": "feminina"},
    {"id": "pm_alex", "label": "Alex", "language": "pt-BR", "gender": "masculina"},
    {"id": "pm_santa", "label": "Santa", "language": "pt-BR", "gender": "masculina"},
    {"id": "af_heart", "label": "Heart", "language": "en-US", "gender": "feminina"},
    {"id": "af_bella", "label": "Bella", "language": "en-US", "gender": "feminina"},
    {"id": "am_michael", "label": "Michael", "language": "en-US", "gender": "masculina"},
    {"id": "am_fenrir", "label": "Fenrir", "language": "en-US", "gender": "masculina"},
    {"id": "bf_emma", "label": "Emma", "language": "en-GB", "gender": "feminina"},
    {"id": "bf_isabella", "label": "Isabella", "language": "en-GB", "gender": "feminina"},
    {"id": "bm_george", "label": "George", "language": "en-GB", "gender": "masculina"},
    {"id": "bm_fable", "label": "Fable", "language": "en-GB", "gender": "masculina"},
]
VOICE_LANGUAGE = {voice["id"]: voice["language"] for voice in KOKORO_VOICES}
DEFAULT_VOICE = {"pt-BR": "pf_dora", "en-US": "af_heart", "en-GB": "bf_emma"}


def voice_for(organization, language: str) -> str:
    """Per-language preference first, then the legacy single voice if it speaks the language, then the default."""
    preferred = (getattr(organization, "voices", None) or {}).get(language)
    for candidate in (preferred, getattr(organization, "voice", None)):
        if candidate and VOICE_LANGUAGE.get(candidate) == language:
            return candidate
    return DEFAULT_VOICE.get(language, "pf_dora")


class LocalVoice:
    """Records voice intent; synthesis happens in the worker with Kokoro."""

    def __init__(self, voice: str = "pf_dora"):
        self.voice = voice

    def synthesize(self, text: str) -> Artifact:
        return Artifact(
            uri=f"kokoro://{self.voice}/{stable_id(text)}",
            kind="audio",
            metadata={"engine": "kokoro", "voice": self.voice},
        )


class SimulatedPublisher:
    def __init__(self, platform: str):
        self.platform = platform

    def publish(self, request: PublishRequest) -> PublishResult:
        external_id = f"sim-{self.platform}-{stable_id(request.idempotency_key)}"
        return PublishResult(external_id=external_id, url=f"https://example.invalid/{external_id}")


class YouTubePublisher:
    """Small HTTP adapter; credentials are supplied only through environment settings."""

    def __init__(self, settings: Settings, access_token: str | None = None):
        token = access_token or settings.youtube_access_token
        if not token:
            raise ValueError("YOUTUBE_ACCESS_TOKEN is required for live publishing")
        self.base = settings.youtube_api_base
        self.token = token

    def publish(self, request: PublishRequest) -> PublishResult:
        path = Path(request.artifact_uri)
        metadata = {
            "snippet": {"title": request.title, "description": request.description},
            "status": {"privacyStatus": "private", "containsSyntheticMedia": True},
        }
        with path.open("rb") as video:
            response = httpx.post(
                f"{self.base}/videos",
                params={"part": "snippet,status", "uploadType": "multipart"},
                headers={"Authorization": f"Bearer {self.token}"},
                files={
                    "metadata": ("metadata.json", json.dumps(metadata), "application/json"),
                    "media": (path.name, video, "video/mp4"),
                },
                timeout=120,
            )
        response.raise_for_status()
        external_id = response.json()["id"]
        return PublishResult(external_id=external_id, url=f"https://youtu.be/{external_id}", simulated=False)


class TikTokPublisher:
    """Uses TikTok's direct-post initialization; upload URL remains platform controlled."""

    def __init__(self, settings: Settings, access_token: str | None = None):
        token = access_token or settings.tiktok_access_token
        if not token:
            raise ValueError("TIKTOK_ACCESS_TOKEN is required for live publishing")
        self.base = settings.tiktok_api_base
        self.token = token

    def publish(self, request: PublishRequest) -> PublishResult:
        size = Path(request.artifact_uri).stat().st_size
        response = httpx.post(
            f"{self.base}/post/publish/video/init/",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json; charset=UTF-8"},
            json={
                "post_info": {"title": request.title, "privacy_level": "SELF_ONLY", "disable_comment": False},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()["data"]
        with Path(request.artifact_uri).open("rb") as video:
            upload = httpx.put(data["upload_url"], content=video.read(), headers={"Content-Type": "video/mp4"}, timeout=120)
        upload.raise_for_status()
        return PublishResult(external_id=data["publish_id"], simulated=False)


def publisher_for(platform: str, live: bool, settings: Settings, access_token: str | None = None):
    if not live:
        return SimulatedPublisher(platform)
    if not settings.allow_live_publish:
        raise ValueError("Live publishing is disabled")
    if platform == "youtube":
        return YouTubePublisher(settings, access_token)
    if platform == "tiktok":
        return TikTokPublisher(settings, access_token)
    raise ValueError(f"Unsupported live platform: {platform}")


class YouTubeMetrics:
    def __init__(self, token: str):
        self.token = token

    def fetch(self, video_id: str) -> dict[str, int]:
        response = httpx.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": video_id},
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        if not items:
            raise ValueError("YouTube video was not found")
        stats = items[0]["statistics"]
        return {
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "shares": 0,
        }


class TikTokMetrics:
    def __init__(self, token: str):
        self.token = token

    def fetch(self, video_id: str) -> dict[str, int]:
        response = httpx.post(
            "https://open.tiktokapis.com/v2/video/query/",
            params={"fields": "id,like_count,comment_count,share_count,view_count"},
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json={"filters": {"video_ids": [video_id]}},
            timeout=30,
        )
        response.raise_for_status()
        videos = response.json().get("data", {}).get("videos", [])
        if not videos:
            raise ValueError("TikTok video was not found")
        stats = videos[0]
        return {
            "views": int(stats.get("view_count", 0)),
            "likes": int(stats.get("like_count", 0)),
            "comments": int(stats.get("comment_count", 0)),
            "shares": int(stats.get("share_count", 0)),
        }


def metrics_for(platform: str, access_token: str):
    if platform == "youtube":
        return YouTubeMetrics(access_token)
    if platform == "tiktok":
        return TikTokMetrics(access_token)
    raise ValueError("Metrics are not available for this platform")


def publication_status(platform: str, access_token: str, external_id: str) -> str:
    headers = {"Authorization": f"Bearer {access_token}"}
    if platform == "youtube":
        response = httpx.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "status,processingDetails", "id": external_id},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        if not items:
            return "failed"
        processing = items[0].get("processingDetails", {}).get("processingStatus")
        return {"succeeded": "published", "failed": "failed"}.get(processing, "processing")
    if platform == "tiktok":
        response = httpx.post(
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
            headers={**headers, "Content-Type": "application/json; charset=UTF-8"},
            json={"publish_id": external_id},
            timeout=30,
        )
        response.raise_for_status()
        remote = response.json().get("data", {}).get("status", "")
        return {
            "PUBLISH_COMPLETE": "published",
            "FAILED": "failed",
        }.get(remote, "processing")
    raise ValueError("Publication status is not available for this platform")
