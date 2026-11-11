import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai import AIProvider, safe_complete
from .config import Settings
from .models import Asset, Render, ResearchDossier, Scene, ScriptVersion
from .retention import shots_for
from .storage import Storage
from .textutil import normalize

WORDS_PER_SECOND = 2.6
CTA_PATTERN = re.compile(r"\b(siga|inscreva|segue|follow|subscribe|like)\b", re.IGNORECASE)


@dataclass
class GateResult:
    passed: bool
    score: float
    issues: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    cost_cents: int = 0


CRITIC_SYSTEM = """Você é editor-chefe de um canal de vídeos explicativos. Avalie o roteiro com rigor.
Critérios (0-100 cada): factuality (afirmações sustentadas pelo dossiê, sem invenções), hook (prende nos 3 primeiros
segundos), pacing (ritmo, frases curtas, virada no meio), clarity (fácil de entender falado).
safety_ok=false se houver desinformação perigosa, discurso de ódio, conteúdo sexual, violação de direitos ou tema proibido.
Formato JSON: {"factuality": int, "hook": int, "pacing": int, "clarity": int, "safety_ok": bool, "issues": [str]}"""


def banned_hits(text: str, banned: list[str]) -> list[str]:
    haystack = normalize(text)
    return [term for term in banned if term.strip() and normalize(term.strip()) in haystack]


def heuristic_script_review(script: ScriptVersion, dossier: ResearchDossier | None, duration_seconds: int) -> GateResult:
    lines = [line for line in script.content.split("\n") if line.strip()]
    words = len(script.content.split())
    target = duration_seconds * WORDS_PER_SECOND
    issues: list[str] = []
    hook = 25 if lines and (lines[0].strip().endswith("?") or len(lines[0].split()) <= 14) else 10
    if hook < 25:
        issues.append("Gancho longo ou fraco na primeira linha")
    length = 25 if target and abs(words - target) / target <= 0.35 else 10
    if length < 25:
        issues.append(f"Tamanho fora do alvo: {words} palavras para ~{int(target)}")
    facts = len(dossier.facts) if dossier else 0
    sourcing = 25 if facts >= 3 else 15 if dossier else 5
    if facts < 3:
        issues.append("Poucos fatos com fonte no dossiê")
    structure = 15 if len(lines) >= 4 and lines and CTA_PATTERN.search(lines[-1]) else 8
    score = float(hook + length + sourcing + structure)
    return GateResult(passed=False, score=score, issues=issues, detail={"mode": "heuristic", "words": words, "target_words": int(target)})


def review_script(
    ai: AIProvider | None,
    script: ScriptVersion,
    dossier: ResearchDossier | None,
    duration_seconds: int,
    threshold: int,
    banned: list[str],
) -> GateResult:
    hits = banned_hits(script.content, banned)
    result = safe_complete(
        ai,
        CRITIC_SYSTEM,
        json.dumps(
            {
                "roteiro": script.content,
                "duracao_alvo_s": duration_seconds,
                "dossie": {"resumo": dossier.summary, "fatos": dossier.facts[:30]} if dossier else None,
                "temas_proibidos": banned,
            },
            ensure_ascii=False,
        ),
        max_tokens=900,
    )
    if result:
        data = result.data
        parts = {key: float(data.get(key) or 0) for key in ("factuality", "hook", "pacing", "clarity")}
        score = round(parts["factuality"] * 0.4 + parts["hook"] * 0.25 + parts["pacing"] * 0.2 + parts["clarity"] * 0.15, 1)
        review = GateResult(
            passed=False,
            score=score,
            issues=[str(issue)[:300] for issue in data.get("issues") or []][:10],
            detail={"mode": "ai", **parts, "safety_ok": bool(data.get("safety_ok", True))},
            cost_cents=result.cost_cents,
        )
    else:
        review = heuristic_script_review(script, dossier, duration_seconds)
    safe = review.detail.get("safety_ok", True) and not hits
    if hits:
        review.issues.insert(0, f"Tema proibido citado: {', '.join(hits)}")
    if not review.detail.get("safety_ok", True):
        review.issues.insert(0, "Revisão de segurança reprovou o roteiro")
    review.passed = safe and review.score >= threshold
    review.detail["threshold"] = threshold
    return review


def _probe(path: str) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout or "{}") if result.returncode == 0 else {}


def _media_stats(path: str) -> tuple[float | None, float]:
    """Mean loudness (dB) and black-frame seconds, from one FFmpeg pass."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None, 0.0
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path, "-vf", "blackdetect=d=0.5:pix_th=0.05", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    volume = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    black = sum(float(value) for value in re.findall(r"black_duration:([\d.]+)", result.stderr))
    return (float(volume.group(1)) if volume else None), black


def rights_review(db: Session, script_version_id: int, settings: Settings) -> tuple[list[str], dict[str, Any]]:
    scenes = list(db.scalars(select(Scene).where(Scene.script_version_id == script_version_id)))
    issues: list[str] = []
    fair_use_seconds = 0.0
    total = sum(scene.duration_seconds for scene in scenes) or 1
    for shots in shots_for(db, [scene.id for scene in scenes]).values():
        for shot in shots:
            asset = db.get(Asset, shot.asset_id) if shot.asset_id else None
            meta = (asset.metadata_json or {}) if asset else {}
            if asset and meta.get("origin") == "auto" and not (meta.get("license") and meta.get("attribution")):
                issues.append(f"Mídia {asset.id} sem licença ou crédito")
            if meta.get("fair_use"):
                if shot.duration > settings.fair_use_max_clip_seconds + 0.01:
                    issues.append(f"Clipe de terceiros com {shot.duration:.1f}s (máx. {settings.fair_use_max_clip_seconds:.0f}s)")
                fair_use_seconds += shot.duration
    ratio = fair_use_seconds / total
    if ratio > settings.fair_use_max_ratio + 0.001:
        issues.append(f"{ratio:.0%} do vídeo vem de clipes de terceiros (máx. {settings.fair_use_max_ratio:.0%})")
    return issues, {"fair_use_seconds": round(fair_use_seconds, 1), "fair_use_ratio": round(ratio, 3)}


def review_render(db: Session, render: Render, storage: Storage, settings: Settings) -> GateResult:
    scenes = list(db.scalars(select(Scene).where(Scene.script_version_id == render.script_version_id)))
    expected = sum(scene.duration_seconds for scene in scenes)
    blocking, detail = rights_review(db, render.script_version_id, settings)
    warnings: list[str] = []
    if not all(scene.narration.strip() for scene in scenes):
        blocking.append("Cena sem narração ou legenda")
    if render.status != "completed" or not render.artifact_uri:
        blocking.append(f"Render não concluído ({render.status}): {render.error or ''}".strip())
    elif render.artifact_kind != "video":
        message = "Render gerou manifesto em vez de vídeo (FFmpeg indisponível)"
        (warnings if settings.app_env == "development" else blocking).append(message)
    else:
        with storage.local_copy(render.artifact_uri) as path:
            probe = _probe(str(path))
            volume, black = _media_stats(str(path))
        duration = float((probe.get("format") or {}).get("duration") or 0)
        streams = {stream.get("codec_type") for stream in probe.get("streams") or []}
        detail.update({"duration": duration, "expected": expected, "mean_volume_db": volume, "black_seconds": black})
        if probe and expected and not (0.7 * expected <= duration <= 1.8 * expected):
            blocking.append(f"Duração {duration:.0f}s muito diferente do planejado ({expected:.0f}s)")
        if probe and "audio" not in streams:
            blocking.append("Vídeo sem faixa de áudio")
        if volume is not None and volume < -45:
            blocking.append(f"Áudio quase mudo ({volume:.0f} dB): verifique a narração Kokoro")
        if duration and black / duration > 0.35:
            blocking.append(f"{black:.0f}s de tela preta")
    score = max(0.0, 100.0 - 25 * len(blocking) - 5 * len(warnings))
    return GateResult(passed=not blocking, score=score, issues=blocking + warnings, detail={**detail, "warnings": warnings})
