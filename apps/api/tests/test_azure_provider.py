import json

import httpx
import pytest

from app.ai import AIError, AzureOpenAIProvider, parse_json_object
from app.config import Settings

SETTINGS = dict(
    azure_openai_endpoint="https://chat.example.test/",
    azure_openai_api_key="secret-key",
    azure_openai_chat_deployment="gpt-5.6-sol",
)


def provider_with(handler, **overrides) -> tuple[AzureOpenAIProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(record))
    return AzureOpenAIProvider(Settings(**{**SETTINGS, **overrides}), client=client), seen


def reply(content: str, finish_reason: str = "stop", completion_tokens: int = 40):
    return lambda request: httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": completion_tokens},
        },
    )


def test_reasoning_payload_matches_gpt5_contract():
    provider, seen = provider_with(reply('{"ok": true}'))
    result = provider.complete_json("sys", "user", max_tokens=800)
    request = seen[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://chat.example.test/openai/deployments/gpt-5.6-sol/chat/completions?api-version=2024-10-21"
    assert "temperature" not in body and "max_tokens" not in body
    assert body["max_completion_tokens"] == 16000 and body["reasoning_effort"] == "low"
    assert body["response_format"] == {"type": "json_object"}
    assert request.headers["api-key"] == "secret-key"
    assert request.headers["authorization"] == "Bearer secret-key"
    assert result.data == {"ok": True} and result.cost_cents == 1


def test_classic_models_keep_max_tokens_and_temperature():
    provider, seen = provider_with(reply('{"ok": true}'), azure_openai_reasoning=False)
    provider.complete_json("sys", "user", max_tokens=800)
    body = json.loads(seen[0].content)
    assert body["max_tokens"] == 800 and body["temperature"] == 0.4 and "max_completion_tokens" not in body


def test_effort_can_be_disabled_and_budget_raised():
    provider, seen = provider_with(reply('{"ok": true}'), azure_openai_reasoning_effort="", azure_openai_min_completion_tokens=1000)
    provider.complete_json("sys", "user", max_tokens=3500)
    body = json.loads(seen[0].content)
    assert "reasoning_effort" not in body and body["max_completion_tokens"] == 3500


def test_reasoning_that_eats_the_budget_is_a_clear_error():
    provider, _ = provider_with(reply("", finish_reason="length", completion_tokens=16000))
    with pytest.raises(AIError, match="consumido pelo raciocínio"):
        provider.complete_json("sys", "user")


def test_gateway_errors_and_unreachable_hosts_are_reported():
    provider, _ = provider_with(lambda request: httpx.Response(401, text="invalid subscription key"))
    with pytest.raises(AIError, match="401: invalid subscription key"):
        provider.complete_json("sys", "user")

    def offline(request):
        raise httpx.ConnectError("name resolution failed")

    provider, _ = provider_with(offline)
    with pytest.raises(AIError, match="Sem conexão com https://chat.example.test"):
        provider.complete_json("sys", "user")


def test_json_wrapped_in_markdown_is_accepted():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(AIError):
        parse_json_object("sem json aqui")
    with pytest.raises(AIError):
        parse_json_object("[1, 2]")


def test_check_connection_reports_json_and_vision_without_the_key():
    answers = iter(['{"ok": true}', '{"color": "red"}'])
    provider, seen = provider_with(lambda request: reply(next(answers))(request))
    report = provider.check_connection()
    assert report["ok"] and report["json"] and report["vision"] and report["vision_answer"] == "red"
    assert "secret-key" not in json.dumps(report)
    vision_body = json.loads(seen[1].content)
    assert vision_body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_check_connection_endpoint(client, monkeypatch):
    assert client.post("/api/v1/autopilot/integrations/test").status_code == 409
    from app.routers import autopilot as router

    settings = Settings(**SETTINGS)
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    monkeypatch.setattr(AzureOpenAIProvider, "check_connection", lambda self: {"ok": False, "endpoint": self.base, "error": "401"})
    report = client.post("/api/v1/autopilot/integrations/test").json()
    assert report == {"ok": False, "endpoint": "https://chat.example.test", "error": "401"}
