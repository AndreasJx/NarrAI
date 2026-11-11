import json
from dataclasses import dataclass, field
from typing import Any

from .adapters import LocalLLM
from .ai import AIProvider, safe_complete
from .models import ResearchDossier
from .textutil import LANGUAGE_NAME

WORDS_PER_SECOND = 2.6

SCRIPT_SYSTEM = """Você é roteirista de vídeos explicativos verticais (Shorts, Reels, TikTok) focados em retenção.
Regras:
- Primeira linha: gancho forte em até 3 segundos (pergunta, contradição ou revelação), sem saudação.
- Cada linha é uma cena curta (8 a 22 palavras), em linguagem falada.
- Toda afirmação factual deve citar os ids dos fatos do dossiê que a sustentam; não invente fatos.
- Inclua uma virada no meio e a revelação principal perto de 60% do vídeo.
- Termine com um fechamento e uma chamada para seguir.
Formato JSON: {"title": str, "description": str, "title_variants": [str, str], "hook_style": "question"|"contradiction"|"reveal"|"statement",
"lines": [{"text": str, "citations": [str]}]}"""


@dataclass
class ScriptDraft:
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    cost_cents: int = 0
    author: str = "local-llm"


def _dossier_prompt(dossier: ResearchDossier | None) -> str:
    if not dossier:
        return "Sem dossiê: use apenas conhecimento geral consensual e evite números específicos."
    facts = [{"id": fact.get("id"), "text": fact.get("text"), "source": fact.get("source_url")} for fact in dossier.facts[:30]]
    return json.dumps(
        {"resumo": dossier.summary, "fatos": facts, "angulos": dossier.angles[:6], "ganchos": dossier.hooks[:6]},
        ensure_ascii=False,
    )


def hook_style(first_line: str) -> str:
    return "question" if first_line.strip().endswith("?") else "statement"


def write_script(
    ai: AIProvider | None,
    *,
    topic: str,
    audience: str,
    objective: str,
    language: str,
    duration_seconds: int,
    tone: str,
    dossier: ResearchDossier | None,
    playbook: str = "",
) -> ScriptDraft:
    target_words = int(duration_seconds * WORDS_PER_SECOND)
    result = safe_complete(
        ai,
        SCRIPT_SYSTEM,
        (
            f"Idioma do roteiro: {LANGUAGE_NAME.get(language, language)} (escreva tudo nesse idioma).\n"
            f"Tema: {topic}\nPúblico: {audience}\nObjetivo: {objective}\nTom: {tone}\n"
            f"Duração alvo: {duration_seconds}s (cerca de {target_words} palavras no total).\n"
            f"Aprendizados do canal (playbook):\n{playbook or 'nenhum ainda'}\n"
            f"Dossiê de pesquisa:\n{_dossier_prompt(dossier)}"
        ),
        max_tokens=2500,
    )
    lines = [line for line in (result.data.get("lines") or []) if str(line.get("text", "")).strip()] if result else []
    if result and len(lines) >= 3:
        texts = [" ".join(str(line["text"]).split()) for line in lines]
        return ScriptDraft(
            content="\n".join(texts),
            metadata={
                "provider": ai.name,
                "language": language,
                "title": str(result.data.get("title") or topic)[:300],
                "description": str(result.data.get("description") or "")[:4000],
                "title_variants": [str(item)[:300] for item in (result.data.get("title_variants") or [])][:3],
                "hook_style": result.data.get("hook_style") or hook_style(texts[0]),
                "citations": [list(line.get("citations") or []) for line in lines],
                "usage": result.usage,
            },
            cost_cents=result.cost_cents,
            author=ai.name,
        )
    local = LocalLLM().generate(topic, audience, dossier.summary if dossier else "", duration_seconds, language)
    first = local.text.split("\n", 1)[0]
    return ScriptDraft(
        content=local.text,
        metadata={
            **local.metadata,
            "title": topic[:300],
            "description": "",
            "title_variants": [topic[:300], first[:300]],
            "hook_style": hook_style(first),
            "citations": [],
        },
    )
