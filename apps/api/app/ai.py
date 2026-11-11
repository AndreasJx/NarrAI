import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import Settings, get_settings

logger = logging.getLogger("narra.ai")
# 16x16 solid red PNG, inline so the vision check does not depend on any external host.
TEST_IMAGE = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR42mO4IyJCEmIY1TCqYfhqAAACcQQQFd0BdQAAAABJRU5ErkJggg=="
)


class AIError(RuntimeError):
    pass


def parse_json_object(text: str) -> dict[str, Any]:
    """JSON mode should return a bare object, but some gateways wrap it in Markdown fences or prose."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AIError("Resposta da IA não é JSON válido") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIError("Resposta da IA não é JSON válido") from exc
    if not isinstance(data, dict):
        raise AIError("Resposta da IA não é um objeto JSON")
    return data


@dataclass
class AIResult:
    data: dict[str, Any]
    cost_cents: int = 0
    usage: dict[str, int] = field(default_factory=dict)


class AIProvider(Protocol):
    name: str

    def complete_json(self, system: str, user: str, images: list[str] | None = None, max_tokens: int = 2000) -> AIResult: ...

    def transcribe(self, audio: Path) -> tuple[str, int]: ...


class AzureOpenAIProvider:
    """Azure OpenAI over plain HTTP: one chat deployment (with vision) and an optional transcription deployment."""

    name = "azure-openai"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.base = settings.azure_openai_endpoint.rstrip("/")
        key = settings.azure_openai_api_key
        # Azure expects "api-key"; corporate gateways in front of it often expect a bearer token instead.
        self.client = client or httpx.Client(timeout=settings.azure_openai_timeout_seconds)
        self.client.headers.update({"api-key": key, "Authorization": f"Bearer {key}"})

    def _url(self, deployment: str, path: str) -> str:
        return f"{self.base}/openai/deployments/{deployment}/{path}?api-version={self.settings.azure_openai_api_version}"

    def cost_for(self, prompt_tokens: int, completion_tokens: int) -> int:
        cents = (
            prompt_tokens * self.settings.azure_input_cents_per_mtok
            + completion_tokens * self.settings.azure_output_cents_per_mtok
        ) / 1_000_000
        return math.ceil(cents)

    def chat_payload(self, messages: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
        payload: dict[str, Any] = {"messages": messages, "response_format": {"type": "json_object"}}
        if self.settings.azure_openai_reasoning:
            # GPT-5 / o-series reject max_tokens and non-default temperature; reasoning tokens count against this limit.
            payload["max_completion_tokens"] = max(max_tokens, self.settings.azure_openai_min_completion_tokens)
            if self.settings.azure_openai_reasoning_effort:
                payload["reasoning_effort"] = self.settings.azure_openai_reasoning_effort
        else:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = 0.4
        return payload

    def complete_json(self, system: str, user: str, images: list[str] | None = None, max_tokens: int = 2000) -> AIResult:
        content: Any = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": url, "detail": "low"}} for url in images
            ]
        messages = [
            {"role": "system", "content": system + "\nResponda somente com um objeto JSON válido."},
            {"role": "user", "content": content},
        ]
        try:
            response = self.client.post(
                self._url(self.settings.azure_openai_chat_deployment, "chat/completions"),
                json=self.chat_payload(messages, max_tokens),
            )
        except httpx.HTTPError as exc:
            raise AIError(f"Sem conexão com {self.base}: {exc}") from exc
        if response.status_code >= 400:
            raise AIError(f"Azure OpenAI {response.status_code}: {response.text[:300]}")
        body = response.json()
        usage = body.get("usage") or {}
        choice = (body.get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        prompt, completion = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        if not text:
            if choice.get("finish_reason") == "length":
                raise AIError(
                    f"Resposta vazia: o limite de {completion} tokens foi consumido pelo raciocínio "
                    "(aumente AZURE_OPENAI_MIN_COMPLETION_TOKENS ou reduza AZURE_OPENAI_REASONING_EFFORT)"
                )
            raise AIError(f"Resposta vazia da IA (finish_reason={choice.get('finish_reason')})")
        return AIResult(
            data=parse_json_object(text),
            cost_cents=self.cost_for(prompt, completion),
            usage={"prompt_tokens": prompt, "completion_tokens": completion},
        )

    def check_connection(self) -> dict[str, Any]:
        """Smallest real round trip: JSON mode and, separately, vision. Never includes the key in the report."""
        report: dict[str, Any] = {
            "endpoint": self.base,
            "deployment": self.settings.azure_openai_chat_deployment,
            "source": self.settings.azure_openai_config_source,
        }
        started = time.monotonic()
        try:
            result = self.complete_json("Teste de conexão.", 'Responda {"ok": true}.', max_tokens=50)
            report.update(ok=bool(result.data.get("ok")), json=True, usage=result.usage, cost_cents=result.cost_cents)
        except AIError as exc:
            report.update(ok=False, json=False, error=str(exc)[:500])
            report["latency_ms"] = int((time.monotonic() - started) * 1000)
            return report
        report["latency_ms"] = int((time.monotonic() - started) * 1000)
        try:
            vision = self.complete_json(
                "Descreva imagens.", 'Qual a cor dominante da imagem? Responda {"color": "<cor em inglês>"}.',
                images=[TEST_IMAGE], max_tokens=50,
            )
            report.update(vision=True, vision_answer=str(vision.data.get("color", ""))[:40])
        except AIError as exc:
            report.update(vision=False, vision_error=str(exc)[:300])
        return report

    def transcribe(self, audio: Path) -> tuple[str, int]:
        deployment = self.settings.azure_openai_transcribe_deployment
        if not deployment:
            raise AIError("AZURE_OPENAI_TRANSCRIBE_DEPLOYMENT não configurado")
        with audio.open("rb") as handle:
            response = self.client.post(
                self._url(deployment, "audio/transcriptions"),
                files={"file": (audio.name, handle, "audio/mpeg")},
                data={"response_format": "verbose_json"},
            )
        if response.status_code >= 400:
            raise AIError(f"Transcrição falhou {response.status_code}: {response.text[:300]}")
        body = response.json()
        minutes = math.ceil(float(body.get("duration") or 60) / 60)
        segments = body.get("segments") or []
        if segments:
            text = "\n".join(f"[{int(seg.get('start', 0))}s] {seg.get('text', '').strip()}" for seg in segments)
        else:
            text = body.get("text", "")
        return text, minutes * self.settings.azure_transcribe_cents_per_minute


_override: AIProvider | None = None


def use_provider(provider: AIProvider | None) -> None:
    """Swap the provider (tests and scripts); None restores the configured one."""
    global _override
    _override = provider


def ai_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.azure_openai_endpoint and settings.azure_openai_api_key and settings.azure_openai_chat_deployment)


def get_ai(settings: Settings | None = None) -> AIProvider | None:
    if _override is not None:
        return _override
    settings = settings or get_settings()
    if not ai_configured(settings):
        return None
    return AzureOpenAIProvider(settings)


def safe_complete(
    ai: AIProvider | None, system: str, user: str, images: list[str] | None = None, max_tokens: int = 2000
) -> AIResult | None:
    """Returns None when there is no provider or the call fails, so every stage can fall back to local logic."""
    if ai is None:
        return None
    try:
        return ai.complete_json(system, user, images=images, max_tokens=max_tokens)
    except Exception as exc:  # noqa: BLE001 - AI is best effort; callers fall back
        logger.warning("AI call failed: %s", exc)
        return None
