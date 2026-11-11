import json
import logging
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from .ai import AIProvider, safe_complete
from .config import Settings, get_settings
from .models import Asset, Project, ResearchDossier, Scene
from .storage import ALLOWED_UPLOADS, Storage, signature_matches
from .textutil import keywords, overlap_score

logger = logging.getLogger("narra.media")


def user_agent() -> str:
    """Wikimedia's robot policy rejects clients without contact information in the User-Agent."""
    settings = get_settings()
    return f"NarraBot/0.3 ({settings.media_contact or settings.web_base_url}) httpx/{httpx.__version__}"
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 120 * 1024 * 1024
LICENSED_PROVIDERS = {"pexels", "pixabay", "wikimedia", "openverse", "press-kit"}


@dataclass
class Candidate:
    provider: str
    kind: str
    url: str
    thumb: str
    width: int = 0
    height: int = 0
    license: str = ""
    attribution: str = ""
    source_url: str = ""
    title: str = ""
    duration: float = 0
    clip_start: float = 0
    fair_use: bool = False
    score: float = 0
    reasons: list[str] = field(default_factory=list)


class MediaSearch(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[Candidate]: ...


class PexelsSearch:
    name = "pexels"

    def __init__(self, api_key: str):
        self.headers = {"Authorization": api_key}

    def search(self, query: str, limit: int) -> list[Candidate]:
        photos = httpx.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": limit, "orientation": "portrait"},
            headers=self.headers,
            timeout=30,
        )
        photos.raise_for_status()
        found = [
            Candidate(
                provider=self.name,
                kind="image",
                url=item["src"].get("large2x") or item["src"]["original"],
                thumb=item["src"].get("medium") or item["src"]["original"],
                width=item.get("width", 0),
                height=item.get("height", 0),
                license="Pexels License",
                attribution=f"Foto de {item.get('photographer', 'autor desconhecido')} (Pexels)",
                source_url=item.get("url", ""),
                title=item.get("alt") or "",
            )
            for item in photos.json().get("photos", [])
        ]
        videos = httpx.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": max(2, limit // 2), "orientation": "portrait"},
            headers=self.headers,
            timeout=30,
        )
        videos.raise_for_status()
        for item in videos.json().get("videos", []):
            files = sorted(
                (file for file in item.get("video_files", []) if file.get("file_type") == "video/mp4" and (file.get("height") or 0) <= 1920),
                key=lambda file: file.get("height") or 0,
                reverse=True,
            )
            if not files:
                continue
            found.append(
                Candidate(
                    provider=self.name,
                    kind="video",
                    url=files[0]["link"],
                    thumb=item.get("image", ""),
                    width=files[0].get("width") or 0,
                    height=files[0].get("height") or 0,
                    license="Pexels License",
                    attribution=f"Vídeo de {item.get('user', {}).get('name', 'autor desconhecido')} (Pexels)",
                    source_url=item.get("url", ""),
                    duration=float(item.get("duration") or 0),
                )
            )
        return found


class PixabaySearch:
    name = "pixabay"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, limit: int) -> list[Candidate]:
        response = httpx.get(
            "https://pixabay.com/api/",
            params={"key": self.api_key, "q": query[:100], "image_type": "photo", "orientation": "vertical", "per_page": max(3, limit), "safesearch": "true"},
            timeout=30,
        )
        response.raise_for_status()
        return [
            Candidate(
                provider=self.name,
                kind="image",
                url=item.get("largeImageURL") or item["webformatURL"],
                thumb=item.get("webformatURL", ""),
                width=item.get("imageWidth", 0),
                height=item.get("imageHeight", 0),
                license="Pixabay Content License",
                attribution=f"Imagem de {item.get('user', 'autor desconhecido')} (Pixabay)",
                source_url=item.get("pageURL", ""),
                title=item.get("tags", ""),
            )
            for item in response.json().get("hits", [])
        ]


class WikimediaSearch:
    name = "wikimedia"

    def search(self, query: str, limit: int) -> list[Candidate]:
        response = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": 6,
                "gsrlimit": limit,
                "prop": "imageinfo",
                "iiprop": "url|size|extmetadata",
                "iiurlwidth": 1080,
            },
            headers={"User-Agent": user_agent()},
            timeout=30,
        )
        response.raise_for_status()
        found = []
        for page in (response.json().get("query", {}).get("pages") or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            license_name = (meta.get("LicenseShortName") or {}).get("value", "")
            if not license_name or "fair use" in license_name.lower():
                continue
            artist = (meta.get("Artist") or {}).get("value", "")
            found.append(
                Candidate(
                    provider=self.name,
                    kind="image",
                    url=info.get("thumburl") or info.get("url", ""),
                    thumb=info.get("thumburl") or info.get("url", ""),
                    width=info.get("thumbwidth") or info.get("width", 0),
                    height=info.get("thumbheight") or info.get("height", 0),
                    license=license_name,
                    attribution=f"{_strip_html(artist) or 'Autor desconhecido'} / Wikimedia Commons ({license_name})",
                    source_url=info.get("descriptionurl", ""),
                    title=page.get("title", ""),
                )
            )
        return found


class OpenverseSearch:
    name = "openverse"

    def search(self, query: str, limit: int) -> list[Candidate]:
        response = httpx.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": limit, "license_type": "commercial"},
            headers={"User-Agent": user_agent()},
            timeout=30,
        )
        response.raise_for_status()
        return [
            Candidate(
                provider=self.name,
                kind="image",
                url=item.get("url", ""),
                thumb=item.get("thumbnail") or item.get("url", ""),
                width=item.get("width") or 0,
                height=item.get("height") or 0,
                license=f"CC {item.get('license', '').upper()} {item.get('license_version', '')}".strip(),
                attribution=item.get("attribution") or f"{item.get('creator', 'Autor desconhecido')} (Openverse)",
                source_url=item.get("foreign_landing_url", ""),
                title=item.get("title") or "",
            )
            for item in response.json().get("results", [])
            if item.get("url")
        ]


def _strip_html(value: str) -> str:
    import re

    return " ".join(re.sub(r"<[^>]+>", " ", value).split())[:200]


def search_providers(settings: Settings) -> list[MediaSearch]:
    providers: list[MediaSearch] = []
    if settings.pexels_api_key:
        providers.append(PexelsSearch(settings.pexels_api_key))
    if settings.pixabay_api_key:
        providers.append(PixabaySearch(settings.pixabay_api_key))
    providers += [WikimediaSearch(), OpenverseSearch()]
    return providers


def press_kit_candidates(urls: list[str]) -> list[Candidate]:
    return [
        Candidate(provider="press-kit", kind="image", url=url, thumb=url, license="Press kit oficial", attribution=f"Material oficial de imprensa ({url.split('/')[2] if '//' in url else url})", source_url=url)
        for url in urls
        if url.startswith(("http://", "https://"))
    ]


QUERY_SYSTEM = """Você planeja o visual de um vídeo explicativo vertical. Para cada cena, proponha de 2 a 4 consultas
de busca curtas (em inglês, que rendem mais resultados em bancos de imagem), concretas e visuais: lugares, objetos,
personagens, cenas. Para temas de jogos, filmes ou marcas, inclua o nome próprio (ex.: "Destiny 2014 Tower").
Formato JSON: {"scenes": [{"position": int, "queries": [str]}]}"""

RANK_SYSTEM = """Você é editor de vídeo focado em retenção. Avalie as imagens numeradas para a narração dada.
Critérios: relevância ao que está sendo dito (0-60), qualidade e nitidez em vertical (0-25), impacto visual para prender
atenção (0-15). Formato JSON: {"scores": [{"index": int, "score": int, "reason": str}]}"""


def visual_queries(ai: AIProvider | None, topic: str, scenes: list[Scene], context: str = "") -> tuple[dict[int, list[str]], int]:
    result = safe_complete(
        ai,
        QUERY_SYSTEM,
        json.dumps(
            {"tema": topic, "contexto": context, "cenas": [{"position": s.position, "narracao": s.narration} for s in scenes]},
            ensure_ascii=False,
        ),
        max_tokens=1500,
    )
    planned: dict[int, list[str]] = {}
    if result:
        for item in result.data.get("scenes") or []:
            queries = [str(query)[:100] for query in item.get("queries") or [] if str(query).strip()]
            if queries:
                planned[int(item.get("position", 0))] = queries[:4]
    # Without AI, keep the full topic ("Destiny 1", not just "destiny") and anchor it in the channel niche.
    anchored = " ".join(dict.fromkeys(f"{topic[:60]} {' '.join(keywords(context, 2))}".split()))
    for scene in scenes:
        if scene.position not in planned:
            words = keywords(scene.narration, 2)
            planned[scene.position] = [anchored, f"{topic[:60]} {' '.join(words)}".strip()]
    return planned, result.cost_cents if result else 0


def heuristic_score(narration: str, topic: str, candidate: Candidate) -> float:
    relevance = max(overlap_score(narration, candidate.title), overlap_score(topic, candidate.title)) * 60
    portrait = 25 if candidate.height >= candidate.width > 0 else 12 if candidate.width else 8
    sharp = 15 if max(candidate.width, candidate.height) >= 1080 else 6
    bonus = 10 if candidate.provider == "press-kit" else 0
    return relevance + portrait + sharp + bonus


def rank_candidates(ai: AIProvider | None, narration: str, topic: str, candidates: list[Candidate], shortlist: int = 8) -> tuple[list[Candidate], int]:
    for candidate in candidates:
        candidate.score = heuristic_score(narration, topic, candidate)
    ordered = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    top = [candidate for candidate in ordered if candidate.thumb][:shortlist]
    result = safe_complete(
        ai,
        RANK_SYSTEM,
        f"Tema: {topic}\nNarração da cena: {narration}\nImagens numeradas de 0 a {len(top) - 1} na ordem enviada.",
        images=[candidate.thumb for candidate in top],
        max_tokens=800,
    ) if top else None
    if result:
        for item in result.data.get("scores") or []:
            index = int(item.get("index", -1))
            if 0 <= index < len(top):
                top[index].score = float(item.get("score", 0))
                top[index].reasons.append(str(item.get("reason", ""))[:200])
        ordered = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    return ordered, result.cost_cents if result else 0


def download(url: str, max_bytes: int) -> tuple[bytes, str]:
    with httpx.stream("GET", url, headers={"User-Agent": user_agent()}, timeout=60, follow_redirects=True) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        chunks, total = [], 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("arquivo maior que o limite")
            chunks.append(chunk)
    return b"".join(chunks), content_type


def sniff_type(content: bytes, declared: str) -> str | None:
    candidates = [declared] if declared in ALLOWED_UPLOADS else []
    candidates += [kind for kind in ALLOWED_UPLOADS if kind != declared]
    for content_type in candidates:
        if signature_matches(content_type, content[:32]):
            return content_type
    return None


def fetch_youtube_clip(moment: dict[str, Any], max_seconds: float) -> tuple[bytes, str] | None:
    """Short excerpt for transformative commentary; only used when FAIR_USE_CLIPS_ENABLED is set."""
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp or not moment.get("url"):
        return None
    start = float(moment.get("start") or 0)
    end = min(float(moment.get("end") or start + max_seconds), start + max_seconds)
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "clip.mp4"
        try:
            subprocess.run(
                [ytdlp, "-q", "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b", "--merge-output-format", "mp4",
                 "--download-sections", f"*{start:.1f}-{end:.1f}", "--force-keyframes-at-cuts", "-o", str(target), moment["url"]],
                check=True,
                capture_output=True,
                timeout=240,
            )
            return target.read_bytes(), "video/mp4"
        except Exception as exc:  # noqa: BLE001 - clips are optional
            logger.info("Clip download failed for %s: %s", moment.get("url"), exc)
            return None


@dataclass
class MediaOutcome:
    by_scene: dict[int, list[Asset]] = field(default_factory=dict)
    clips: dict[int, Asset] = field(default_factory=dict)
    cost_cents: int = 0
    searched: int = 0


def _store(db: Session, project: Project, storage: Storage, content: bytes, content_type: str, candidate: Candidate) -> Asset:
    kind, ext, _ = ALLOWED_UPLOADS[content_type]
    key = f"orgs/{project.organization_id}/projects/{project.id}/media/{uuid.uuid4().hex}{ext}"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"media{ext}"
        path.write_bytes(content)
        storage.put_file(path, key, content_type)
    asset = Asset(
        project_id=project.id,
        kind=kind,
        uri=key,
        filename=(candidate.title or candidate.provider)[:200] + ext,
        content_type=content_type,
        size_bytes=len(content),
        status="ready",
        metadata_json={
            "origin": "auto",
            "provider": candidate.provider,
            "license": candidate.license,
            "attribution": candidate.attribution,
            "source_url": candidate.source_url,
            "score": round(candidate.score, 1),
            "reasons": candidate.reasons,
            "fair_use": candidate.fair_use,
            "duration": candidate.duration,
            "clip_start": candidate.clip_start,
        },
    )
    db.add(asset)
    db.flush()
    return asset


def _fetch_candidate(db: Session, project: Project, storage: Storage, candidate: Candidate) -> Asset | None:
    limit = MAX_VIDEO_BYTES if candidate.kind == "video" else MAX_IMAGE_BYTES
    # Some hosts (e.g. Flickr behind Openverse) refuse direct downloads; the provider thumbnail is the fallback.
    urls = [candidate.url] + ([candidate.thumb] if candidate.kind == "image" and candidate.thumb and candidate.thumb != candidate.url else [])
    for url in urls:
        try:
            content, declared = download(url, limit)
        except Exception as exc:  # noqa: BLE001 - try the fallback, then the next candidate
            logger.info("Download failed %s: %s", url, exc)
            continue
        content_type = sniff_type(content, declared)
        if content_type and ALLOWED_UPLOADS[content_type][0] == candidate.kind:
            return _store(db, project, storage, content, content_type, candidate)
    return None


def source_media(
    db: Session,
    project: Project,
    scenes: list[Scene],
    storage: Storage,
    settings: Settings,
    ai: AIProvider | None,
    topic: str,
    dossier: ResearchDossier | None = None,
    press_kit_urls: list[str] | None = None,
    per_scene: int = 2,
    context: str = "",
) -> MediaOutcome:
    outcome = MediaOutcome()
    queries, cost = visual_queries(ai, topic, scenes, context)
    ranking_topic = f"{topic} {context}".strip()
    outcome.cost_cents += cost
    providers = search_providers(settings)
    press = press_kit_candidates(press_kit_urls or [])
    used_urls: set[str] = set()
    for scene in scenes:
        candidates: list[Candidate] = list(press)
        for query in queries.get(scene.position, [])[:3]:
            for provider in providers:
                try:
                    candidates += provider.search(query, 6)
                except Exception as exc:  # noqa: BLE001 - one provider failing must not stop the others
                    logger.info("%s search failed: %s", provider.name, exc)
        candidates = [candidate for candidate in candidates if candidate.url not in used_urls]
        outcome.searched += len(candidates)
        ranked, cost = rank_candidates(ai, scene.narration, ranking_topic, candidates)
        outcome.cost_cents += cost
        chosen: list[Asset] = []
        for candidate in ranked:
            if len(chosen) >= per_scene:
                break
            asset = _fetch_candidate(db, project, storage, candidate)
            if asset:
                used_urls.add(candidate.url)
                chosen.append(asset)
        if chosen:
            outcome.by_scene[scene.id] = chosen

    if settings.fair_use_clips_enabled and dossier and dossier.video_moments:
        turn_scenes = [scene for index, scene in enumerate(scenes) if 0 < index < len(scenes) - 1][::2]
        for scene, moment in zip(turn_scenes, dossier.video_moments):
            fetched = fetch_youtube_clip(moment, settings.fair_use_max_clip_seconds)
            if not fetched:
                continue
            length = min(settings.fair_use_max_clip_seconds, float(moment["end"]) - float(moment["start"]))
            candidate = Candidate(
                provider="youtube",
                kind="video",
                url=moment["url"],
                thumb="",
                license="Uso transformativo (trecho curto com crédito)",
                attribution=f"Trecho de \"{moment.get('title', '')}\" — {moment.get('channel', 'YouTube')} ({moment['url']}&t={int(moment['start'])}s)",
                source_url=f"{moment['url']}&t={int(moment['start'])}s",
                title=moment.get("title", "clip"),
                duration=length,
                fair_use=True,
                score=50,
            )
            outcome.clips[scene.id] = _store(db, project, storage, fetched[0], fetched[1], candidate)
    return outcome
