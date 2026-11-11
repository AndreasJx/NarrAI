import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from .adapters import LocalResearch
from .ai import AIProvider, safe_complete
from .config import Settings
from .models import Brief, Project, ResearchDossier, Source
from .textutil import LANGUAGE_NAME, keywords, overlap_score, sentences

logger = logging.getLogger("narra.research")
TRANSCRIPT_CHARS = 3500
ARTICLE_CHARS = 3500


@dataclass
class Article:
    title: str
    url: str
    content: str
    score: float = 0


@dataclass
class VideoRef:
    video_id: str
    title: str
    channel: str
    views: int = 0
    duration_seconds: int = 0
    transcript: str = ""
    transcript_source: str = "none"

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass
class ResearchOutcome:
    dossier: ResearchDossier
    sources: list[Source] = field(default_factory=list)
    cost_cents: int = 0
    videos: list[VideoRef] = field(default_factory=list)


class TavilySearch:
    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int) -> list[Article]:
        response = httpx.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_raw_content": True,
            },
            timeout=60,
        )
        response.raise_for_status()
        return [
            Article(
                title=item.get("title") or item.get("url", ""),
                url=item.get("url", ""),
                content=(item.get("raw_content") or item.get("content") or "")[:ARTICLE_CHARS],
                score=float(item.get("score") or 0),
            )
            for item in response.json().get("results", [])
            if item.get("url")
        ]


def _iso_duration(value: str) -> int:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


class YouTubeSearch:
    name = "youtube"
    base = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int, language: str) -> list[VideoRef]:
        found = httpx.get(
            f"{self.base}/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max_results,
                "relevanceLanguage": language.split("-")[0],
                "order": "relevance",
                "key": self.api_key,
            },
            timeout=30,
        )
        found.raise_for_status()
        ids = [item["id"]["videoId"] for item in found.json().get("items", []) if item.get("id", {}).get("videoId")]
        if not ids:
            return []
        details = httpx.get(
            f"{self.base}/videos",
            params={"part": "snippet,statistics,contentDetails", "id": ",".join(ids), "key": self.api_key},
            timeout=30,
        )
        details.raise_for_status()
        videos = [
            VideoRef(
                video_id=item["id"],
                title=item["snippet"].get("title", ""),
                channel=item["snippet"].get("channelTitle", ""),
                views=int(item.get("statistics", {}).get("viewCount", 0)),
                duration_seconds=_iso_duration(item.get("contentDetails", {}).get("duration", "")),
            )
            for item in details.json().get("items", [])
        ]
        return sorted(videos, key=lambda video: video.views, reverse=True)

    def popular_titles(self, query: str, language: str, max_results: int = 15) -> list[VideoRef]:
        return self.search(query, max_results, language)


def article_search(settings: Settings) -> TavilySearch | None:
    return TavilySearch(settings.tavily_api_key) if settings.tavily_api_key else None


def video_search(settings: Settings) -> YouTubeSearch | None:
    return YouTubeSearch(settings.youtube_api_key) if settings.youtube_api_key else None


def fetch_captions(video_id: str, language: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    languages = [language, language.split("-")[0], "en", "pt"]
    try:
        api = YouTubeTranscriptApi()
        snippets = [(item.start, item.text) for item in api.fetch(video_id, languages=languages)]
    except AttributeError:
        snippets = [
            (item["start"], item["text"])
            for item in YouTubeTranscriptApi.get_transcript(video_id, languages=languages)  # type: ignore[attr-defined]
        ]
    except Exception as exc:  # noqa: BLE001 - captions are often disabled or blocked
        logger.info("No captions for %s: %s", video_id, exc)
        return None
    return "\n".join(f"[{int(start)}s] {text}" for start, text in snippets)[:TRANSCRIPT_CHARS * 3]


def transcribe_audio(ai: AIProvider, video: VideoRef) -> tuple[str, int] | None:
    """Fallback for videos without captions: first 10 minutes of audio, transcribed by the AI provider."""
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "audio.%(ext)s"
        try:
            subprocess.run(
                [ytdlp, "-q", "-f", "bestaudio[filesize<25M]/bestaudio", "--download-sections", "*0-600",
                 "-x", "--audio-format", "mp3", "-o", str(target), video.url],
                check=True,
                capture_output=True,
                timeout=300,
            )
            audio = next(Path(tmp).glob("audio.*"))
            return ai.transcribe(audio)
        except Exception as exc:  # noqa: BLE001 - optional fallback
            logger.info("Audio transcription failed for %s: %s", video.video_id, exc)
            return None


DOSSIER_SYSTEM = """Você é pesquisador de um canal de vídeos explicativos. A partir de artigos e transcrições de vídeos,
monte um dossiê confiável. Não invente nada que não esteja nas fontes. Formato JSON:
{"summary": str, "facts": [{"id": "f1", "text": str, "source_url": str, "timestamp": int|null}],
"angles": [str], "hooks": [str], "controversies": [str],
"video_moments": [{"video_id": str, "start": int, "end": int, "description": str}]}
video_moments são trechos (5 a 8 s) dos vídeos que ilustram visualmente o tema, úteis como clipes curtos."""


def _moments_from_transcript(video: VideoRef, topic: str, limit: int = 2) -> list[dict]:
    moments = []
    for line in video.transcript.splitlines():
        match = re.match(r"\[(\d+)s\]\s*(.*)", line)
        if match and overlap_score(topic, match.group(2)) >= 0.34:
            start = int(match.group(1))
            moments.append({"video_id": video.video_id, "start": start, "end": start + 6, "description": match.group(2)[:200]})
        if len(moments) >= limit:
            break
    return moments


def _local_dossier(topic: str, articles: list[Article], videos: list[VideoRef]) -> dict:
    facts, index = [], 1
    for article in articles:
        for sentence in sentences(article.content, 2):
            facts.append({"id": f"f{index}", "text": sentence[:400], "source_url": article.url, "timestamp": None})
            index += 1
    moments = [moment for video in videos for moment in _moments_from_transcript(video, topic)]
    base = LocalResearch().research(topic).text
    found = ", ".join(article.title for article in articles[:3])
    return {
        "summary": f"{base} Fontes encontradas: {found}." if found else base,
        "facts": facts,
        "angles": [f"O que quase ninguém sabe sobre {topic}", f"{topic}: mito ou verdade?"],
        "hooks": [f"{topic} não é o que você pensa.", f"Por que {topic}?"],
        "controversies": [],
        "video_moments": moments,
    }


def run_research(db: Session, project: Project, brief: Brief, settings: Settings, ai: AIProvider | None) -> ResearchOutcome:
    language = brief.language or project.language or "pt-BR"
    topic = brief.topic
    query = " ".join([topic, *keywords(brief.objective, 2)]) if brief.objective else topic
    articles: list[Article] = []
    videos: list[VideoRef] = []
    cost = 0

    searcher = article_search(settings)
    if searcher:
        try:
            articles = searcher.search(query, settings.research_article_count)
        except Exception as exc:  # noqa: BLE001 - each source is optional
            logger.warning("Article search failed: %s", exc)
    youtube = video_search(settings)
    if youtube:
        try:
            videos = youtube.search(topic, settings.research_video_count, language)[: settings.research_video_count]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Video search failed: %s", exc)
    for video in videos:
        captions = fetch_captions(video.video_id, language)
        if captions:
            video.transcript, video.transcript_source = captions, "captions"
        elif ai is not None and settings.azure_openai_transcribe_deployment:
            transcribed = transcribe_audio(ai, video)
            if transcribed:
                video.transcript, video.transcript_source = transcribed[0], "ai-transcription"
                cost += transcribed[1]

    result = safe_complete(
        ai,
        DOSSIER_SYSTEM,
        json.dumps(
            {
                "tema": topic,
                "idioma_do_dossie": LANGUAGE_NAME.get(language, language),
                "publico": brief.audience,
                "artigos": [{"title": a.title, "url": a.url, "content": a.content} for a in articles],
                "videos": [
                    {"video_id": v.video_id, "title": v.title, "url": v.url, "views": v.views, "transcript": v.transcript[:TRANSCRIPT_CHARS]}
                    for v in videos
                ],
            },
            ensure_ascii=False,
        ),
        max_tokens=3500,
    )
    data = result.data if result and result.data.get("summary") else _local_dossier(topic, articles, videos)
    if result:
        cost += result.cost_cents
    video_urls = {video.video_id: video for video in videos}
    moments = []
    for moment in data.get("video_moments") or []:
        video = video_urls.get(str(moment.get("video_id")))
        if not video:
            continue
        start = max(0, int(moment.get("start") or 0))
        end = max(start + 2, int(moment.get("end") or start + 6))
        moments.append({**moment, "start": start, "end": end, "url": video.url, "title": video.title, "channel": video.channel})

    provider = "+".join(
        part
        for part in (
            searcher.name if searcher and articles else None,
            youtube.name if youtube and videos else None,
            ai.name if result else None,
        )
        if part
    ) or "local"
    dossier = ResearchDossier(
        project_id=project.id,
        language=language,
        summary=str(data.get("summary", ""))[:8000],
        facts=[fact for fact in data.get("facts") or [] if fact.get("text")][:40],
        angles=[str(item) for item in data.get("angles") or []][:10],
        hooks=[str(item) for item in data.get("hooks") or []][:10],
        controversies=[str(item) for item in data.get("controversies") or []][:10],
        video_moments=moments[:20],
        provider=provider,
        cost_cents=cost,
    )
    db.add(dossier)
    sources = [
        Source(project_id=project.id, title=article.title[:500], url=article.url[:1000], summary=article.content[:800] or article.title, provider="tavily")
        for article in articles
    ] + [
        Source(
            project_id=project.id,
            title=f"Vídeo: {video.title}"[:500],
            url=video.url,
            summary=f"{video.channel} · {video.views} visualizações · transcrição: {video.transcript_source}. "
            + " ".join(re.sub(r"\[\d+s\]\s*", "", video.transcript).split())[:500],
            provider="youtube",
        )
        for video in videos
    ]
    sources.append(
        Source(project_id=project.id, title=f"Dossiê: {topic}"[:500], summary=dossier.summary[:4000] or topic, provider=provider)
    )
    db.add_all(sources)
    db.flush()
    return ResearchOutcome(dossier=dossier, sources=sources, cost_cents=cost, videos=videos)
